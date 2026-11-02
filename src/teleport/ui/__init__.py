"""Tầng giao diện PySide6 (`teleport-gui`); chỉ tầng này import Qt (docs/architecture.md mục 1).

Qt chạy ở thread chính; node chạy trong thread riêng với loop asyncio chuẩn và chỉ được chạm tới
qua `bridge.NodeHost` (không bao giờ gọi `Node` từ thread Qt). Mọi chữ người dùng thấy đi qua
`tr()` / `QCoreApplication.translate` (chuỗi nguồn tiếng Việt, `i18n`); chữ do máy khác đặt
(tên máy, tên file) đi qua `core.display` và hiện dạng chữ thuần, không HTML.

Module: `app` (điểm vào, một bản mỗi thư mục cấu hình, ráp các phần), `bridge` (thread node),
`main_window` (cửa sổ chính, khung trang, khung hai cột), `home` (thành phần của trang HOME: khối căn
giữa, thẻ máy này, chân “Lưu vào”), `tray`, `radar` (model thiết bị dùng chung và câu chữ của nó),
`conversations` (danh sách cuộc trò chuyện ở cột trái, kéo thả), `activity` (hoạt động theo máy, không
Qt), `discover` (trang “Tìm máy mới”: radar vòng tròn, ô nhập IP), `motion` (token chuyển động,
hoạt ảnh dùng chung, có được chạy hoạt ảnh không), `pairing` (hộp ghép đôi, mvp mục 7.2), `transfers`
(điều phối gửi/nhận file), `offer` (hộp hỏi nhận file, mvp mục 7.3), `chat` (luồng chat theo máy
ở khung phải), `chat_bubbles` (bong bóng của lượt truyền, mục lịch sử, mốc thời gian),
`transfers_view` (câu chữ của lượt truyền), `receive_dir` (đổi thư mục nhận),
`send` (lấy đường dẫn, kiểm trước và câu lỗi khi gửi), `texts` (câu chữ dùng chung), `i18n`, `theme`
(token màu, thang chữ, stylesheet), `icons` (icon SVG đóng gói), `fonts` (font điểm nhấn đóng gói),
`widgets` (thành phần dùng chung), `gcguard` (gom rác vòng tham chiếu chỉ trên thread Qt),
`errorlog` (ghi lỗi vào log không kèm nội dung lỗi, mvp N9).
"""
