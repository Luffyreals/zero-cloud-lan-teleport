# Tài liệu

Mọi tài liệu của dự án nằm trong thư mục này (trừ `.claude/CLAUDE.md`, hướng dẫn cho Claude Code, viết tiếng Anh). Giới thiệu dự án và cách cài môi trường phát triển: [README.md](../README.md) ở gốc repo.

## 1. Bản đồ tài liệu

### Sản phẩm & kế hoạch

Đọc theo thứ tự **y_tuong → mvp → ke_hoach**: đi từ “vì sao” tới “cái gì” rồi “thế nào”.

| Tài liệu | Trả lời câu hỏi | Nguồn duy nhất cho | Cập nhật khi |
|---|---|---|---|
| [y_tuong.md](y_tuong.md) | **Vì sao** làm, cho ai, hướng tới đâu? | Nỗi đau, giá trị cốt lõi, trải nghiệm mong muốn, **nguyên tắc sản phẩm**, tầm nhìn sau v1.0 | Đổi định hướng sản phẩm |
| [mvp.md](mvp.md) | Làm **cái gì**, đạt chuẩn nào? | Phạm vi; tính năng & tiêu chí chấp nhận **F1–F12**; yêu cầu phi chức năng **N1–N12**; thông báo lỗi; tiêu chí phát hành | Đổi phạm vi, tính năng hoặc con số chất lượng |
| [ke_hoach.md](ke_hoach.md) | Làm **thế nào**, **khi nào**, đang tới đâu? | Quyết định đã chốt; thiết kế kỹ thuật; lộ trình và **trạng thái giai đoạn**; danh sách phép đo của đợt đo trên thiết bị thật (mã D1…); kiểm thử; rủi ro kỹ thuật; việc cần chốt | Đổi thiết kế, xong một giai đoạn, chốt một câu hỏi |

### Kỹ thuật & quy trình

| Tài liệu | Trả lời câu hỏi | Nguồn duy nhất cho | Cập nhật khi |
|---|---|---|---|
| [architecture.md](architecture.md) | Code chia thế nào, module nào đã có? | Phân tầng, mô hình tiến trình, **trạng thái từng module**, dữ liệu trên đĩa, quy ước viết test (marker, fixture, chỗ test thay được) | Thêm hoặc xong một module |
| [protocol.md](protocol.md) | Byte nào đi trên dây? | Đặc tả giao thức (phiên bản 1) | Mọi thay đổi định dạng trên dây, trong cùng Pull Request |
| [benchmark.md](benchmark.md) | Đo thực tế thì có đạt không? | Số đo thực tế của mvp N1–N12 và kết quả kiểm H1–H5 (mvp mục 4.1): định nghĩa phép đo, môi trường, kết quả, kết luận | Mỗi lần đo |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Làm việc với repo thế nào? | Nhánh, commit, kiểm tra trước Pull Request, phát hành | Đổi quy trình |
| [SECURITY.md](SECURITY.md) | Báo lỗ hổng ở đâu? | Cách báo lỗ hổng, phạm vi, phiên bản được hỗ trợ | Đổi chính sách |
| [CHANGELOG.md](CHANGELOG.md) | Đã thay đổi gì? | Lịch sử thay đổi theo phiên bản | Mỗi thay đổi người dùng nhận thấy |
| [hieu_du_an.md](hieu_du_an.md) | Dự án chạy thế nào, nói bằng lời đơn giản? | Không là nguồn của thông tin nào: ghi chú dễ hiểu về ghép đôi và gửi file qua một ví dụ; khi lệch thì `protocol.md` và `architecture.md` đúng | Đổi luồng ghép đôi hay gửi file |
| [.claude/CLAUDE.md](../.claude/CLAUDE.md) | Claude Code làm việc với repo thế nào? | Luật, lệnh và bẫy dành cho Claude Code; đội subagent và quy trình chạy chúng (luật nền chỉ nhắc lại một câu kèm tham chiếu; không chép con số hay chi tiết thiết kế) | Đổi quy trình, thêm một bẫy |

## 2. Quy tắc đồng bộ

- Mỗi thông tin chỉ ghi đầy đủ ở **một** tài liệu theo bảng trên; nơi khác tham chiếu tới (ví dụ “mvp N4”, “ke_hoach mục 3.4”) thay vì chép lại con số hay đoạn văn.
- y_tuong viết ở mức ý tưởng, không ghi con số yêu cầu hay chi tiết kỹ thuật.
- [README.md](../README.md) ở gốc repo là phần giới thiệu công khai: được tóm tắt lại giá trị, tính năng và lộ trình, nhưng phải khớp với các tài liệu nguồn ở trên.
- Khi lệch nhau: `protocol.md` và `architecture.md` đúng về giao thức và module; mvp đúng về yêu cầu; ke_hoach đúng về thiết kế và tiến độ; y_tuong đúng về định hướng; `.claude/CLAUDE.md` đúng về đội subagent và quy trình chạy chúng.
- Đổi một con số trong mvp thì rà các chỗ tham chiếu tới mã đó. Xong một module thì cập nhật cả `architecture.md` (module) và, khi xong cả giai đoạn, ke_hoach mục 5.1.
- Cập nhật dòng “Cập nhật:” ở đầu y_tuong, mvp, ke_hoach khi sửa nội dung.

## 3. Thuật ngữ

| Thuật ngữ | Nghĩa |
|---|---|
| **Khối** (block) | Đơn vị chia file: 1 MiB. Là đơn vị băm, nối lại và ghi bitfield. |
| **Lượt truyền** (transfer) | Một lần gửi một hoặc nhiều file, có `transfer_id` riêng. |
| **Ghép đôi** (pairing) | Bước xác nhận mã 6 số ở cả hai máy để hai máy tin nhau. |
| **Thiết bị tin cậy** | Thiết bị đã ghép đôi, lưu trong `trusted.json`. |
| **Fingerprint** | SHA-256 của chứng chỉ thiết bị; là định danh được tin cậy (tên thiết bị chỉ để hiển thị). |
| **Bitfield** | Bảng bit đánh dấu khối đã nhận, **đã khớp hash, đã ghi bền xuống đĩa và đã được đánh dấu bền trong `.state`**. |
| **Merkle root** | Hash đại diện cho cả file, tính từ hash các khối. |
| **File tạm** | `.part` (dữ liệu đang nhận), `.state` (trạng thái nối lại của một file) và `transfer.json` (trạng thái mức lượt truyền), nằm trong `<thư mục nhận>/.teleport/<transfer_id>/`. |
| **Nhật ký `.state`** | Trạng thái nối lại của một file, chỉ ghi thêm: mỗi **lần đánh dấu** (16 khối) nối một bản ghi các khối vừa ghi bền kèm hash. Định dạng: [architecture.md](architecture.md) mục 4. |
| **Máy đang ẩn / đang hiện** | Công tắc “Cho máy chưa ghép đôi thấy máy này” đang tắt / đang bật ([mvp.md](mvp.md) F10). |
| **Chế độ chờ ghép đôi** | Màn hình “Chờ ghép đôi” đang mở, hoặc đang chạy `teleport listen` ([mvp.md](mvp.md) F3). |
| **Kết nối ghép đôi / điều khiển / dữ liệu** | Ba loại kết nối trên cùng một cổng (`protocol.md` mục 2). |
| **Node** | Một tiến trình Teleport đang chạy, gắn với một thư mục cấu hình. |
| **Cô lập thiết bị** (AP isolation) | Wi-Fi chặn các máy trong mạng nói chuyện với nhau. |
| **Đợt đo trên thiết bị thật** | Các phép đo cần máy thật thứ hai hay thiết bị khác (USB, điểm phát Wi-Fi, máy macOS), dồn lại làm một lượt khi có thiết bị; danh sách và mã D1… ở [ke_hoach.md](ke_hoach.md) mục 5.4. |

## 4. Quy ước viết

- Viết tiếng Việt; tên định danh, lệnh, tên message giữ nguyên tiếng Anh trong `code`.
- Tên message giao thức viết thường như trong `protocol.md`: `hello`, `offer`, `data_open`…
- Đơn vị: `MiB` cho kích thước kỹ thuật (khối, giới hạn message); `MB`/`GB` cho con số hướng tới người dùng.
- Phiên bản app: `v0.1.0-alpha`, `v1.0.0` (SemVer); phiên bản giao thức đánh số riêng.
- Tham chiếu chéo: `mvp F6`, `mvp N4`, `mvp mục 8`, `ke_hoach mục 3.4`.
- Trạng thái: ✅ đã xong · ⏳ đang làm · ⬜ chưa làm. Riêng giai đoạn ở [ke_hoach.md](ke_hoach.md) mục 5.1 có thêm ⏸: phần “Xong khi” kiểm được ngay đã đạt, chỉ còn phép đo thuộc đợt đo trên thiết bị thật (ke_hoach mục 5.4). Riêng `protocol.md` dùng ✅ đã cài đặt · 📝 đã đặc tả, chưa cài đặt.
