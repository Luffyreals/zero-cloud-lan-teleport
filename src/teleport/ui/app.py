"""Điểm vào `teleport-gui`: tham số, một bản mỗi thư mục cấu hình, ráp cửa sổ + khay + node.

Luồng khởi động (spec P4-3 mục 4): phân tích tham số (`--config-dir D`, `--background`,
`--selftest`); thư mục cấu hình = `--config-dir` › `TELEPORT_HOME` › `paths.config_dir()`, tuyệt
đối; dựng `QApplication` (`setQuitOnLastWindowClosed(False)`); i18n theo ngôn ngữ đã lưu, font điểm
nhấn (`ui.fonts.install`, lỗi thì dùng font hệ thống), chế độ màu và màu nhấn đã lưu
(`theme.set_preference`, trước khi dựng cửa sổ nào nên không nháy màu); `SingleInstance.acquire`;
log ra file (bên dưới); `GuiApp` dựng cửa sổ, khay, rồi chạy node trong `bridge.NodeHost` nếu máy
đã có `device.crt`. Áp hình học cửa sổ đã lưu (bên dưới), rồi hiện cửa sổ trừ khi `--background`, có
khay và node đang khởi động; `app.exec()`.

**Lần chạy đầu** (mvp F1, spec D1; form ở `ui.first_run`):
- Màn lần chạy đầu (WELCOME) chỉ hiện khi `<config_dir>/device.crt` chưa có (`_setup_done`), không
  đọc `first_run_done`: máy đã có danh tính (từ CLI hay bản trước) không bao giờ đi lại màn này. Chưa
  bấm “Bắt đầu” thì không chạy node, không lấy `node.lock`, không quảng bá gì; `--background` khi chưa
  có danh tính vẫn hiện cửa sổ (và khay).
- Giá trị gợi ý (`_show_first_run`, đọc trên thread Qt, chỉ đọc): tên `suggested_device_name` (tên
  đã lưu, không thì hostname, tên dự phòng `Teleport-????` thì rỗng); thư mục nhận đã lưu, không thì
  `paths.default_receive_dir()`; công tắc tự khởi động chỉ khi `autostart.supported()`, bật sẵn trừ
  khi registry ở OTHER/BLOCKED (tắt sẵn, kèm câu `ui.settings.autostart_state_hint`); đọc registry
  lỗi thì bật sẵn, không câu thêm.
- “Đổi…” → `ReceiveDirController.choose_initial` (không node, không lưu); `initial_selected` →
  `first_run.set_receive_dir`; `failed` khi đang WELCOME → lỗi dưới hàng thư mục (không dải thông báo).
- “Bắt đầu” hợp lệ (`start_requested(FirstRunChoice)`, chỉ khi WELCOME) → `_first_run = choice` rồi
  `start_node()`: `NodeOptions` có `name` (None khi trùng gợi ý), `save_args=True`, và thư mục đã chọn
  (khi khác gợi ý; không thì giữ `make_options`). `Node.start` tạo danh tính, lưu tên trước khi quảng
  bá và lưu gốc thật của thư mục khi mở được. “Thử lại”, phím Thử lại (`ui.shortcuts`) hay lệnh
  `show` khi đang ERROR dùng lại `_first_run` (lần trước có thể chưa lưu gì).
- `start_failed(RECEIVE_DIR)` khi thư mục do người dùng chọn: về WELCOME (giữ chữ đã gõ, gợi ý tính
  lại), câu UNAVAILABLE dưới hàng thư mục, tiêu điểm ở “Đổi…”; lỗi khác → màn ERROR như cũ.
- `started`: áp tự khởi động trên thread Qt **trước** `SettingsController.on_started` (rồi
  `_reconcile_autostart` của Cài đặt sửa `settings.autostart` theo registry): bật mà registry khác ON
  → `autostart.enable`; tắt mà registry đang ON → `autostart.disable` (BLOCKED để nguyên); đọc registry
  lỗi coi như OFF. Bật lỗi (và không có dải thư mục nhận hỏng) → dải `first_run.autostart_failed_text`
  kèm nút “Mở Cài đặt” (trang SETTINGS); tắt lỗi chỉ ghi log. Rồi xóa `_first_run`. Mỗi lần
  `started` (cả máy cũ) ghi `first_run_done=True` qua `host.call(_mark_first_run_done)` khi còn
  False: chỉ ghi nhận giao diện đã chạy node được một lần, không quyết định việc hiện màn.
- **Chỗ hở chấp nhận được**: lần bấm đầu thất bại sau khi `Node.start` đã tạo danh tính (cổng bận,
  thư mục hỏng…) rồi người dùng thoát thay vì sửa và bấm lại → lần mở sau không còn màn lần chạy đầu
  (đã có `device.crt`). Tên khác gợi ý thì đã được lưu (cả khi lỗi là RECEIVE_DIR: tên đã lưu, danh
  tính đã tạo); thư mục không mở được thì không lưu (lần sau dùng thư mục mặc định); lựa chọn tự khởi
  động mất (đổi lại được trong Cài đặt).

**Thiết bị** (`MainWindow.devices`, `ui.radar.DeviceListModel`): `NodeHost.node_event` →
`devices.apply`; lúc `started` lấy ảnh chụp `Node.devices()` qua `NodeHost.call` rồi `devices.reset`.
Sự kiện và kết quả của host cũ bị bỏ; dựng host mới (“Thử lại”) thì `devices.clear()` trước. Danh sách
cuộc trò chuyện ở cột trái (`MainWindow.conversations`) và trang “Tìm máy mới” (`MainWindow.discover`,
`ui.discover.DiscoverPage`) dùng chung model đó. Trang “Tìm máy mới”: `pair_requested` →
`pair_device`, `manual_address_entered` → `pair_address`, `notice` của ghép đôi cũng hiện ở thanh
thông báo của trang; bấm máy đã ghép đôi → `MainWindow.open_conversation` (về HOME, chọn cuộc trò
chuyện của máy đó); lựa chọn dạng hiển thị đọc từ
`Node.settings.radar_view` lúc `started` (kết quả của host cũ, lúc đang thoát, hay về sau khi người
dùng đã bấm đổi dạng thì bỏ) và lưu bằng `Node.set_ui_preferences(radar_view=…)`, cả hai qua
`NodeHost.call`; lỗi → WARNING (tên loại lỗi), lựa chọn vẫn giữ trong RAM.

**Cài đặt** (spec D2): trang `ui.settings.SettingsPage` đăng ký ở đây (`window.add_page(SETTINGS)`,
nên ⚙ và phím Cài đặt chỉ có khi chạy qua `GuiApp`), model thiết bị truyền vào đúng một chỗ (`_device_model`);
`SettingsController` (`GuiApp.settings`) nhận host mới (`attach`), `started` (`on_started`), Thoát
(`close_all`) và `shutdown`. “Hủy ghép đôi…” của trang → hộp xác nhận của `PairingController` như ở
danh sách cuộc trò chuyện; “Tìm máy mới” → trang DISCOVER; hàng Thư mục nhận theo
`receive_dir_controller` (`state_changed` →
`page.set_receive_dir(thư mục, thư mục hỏng, đang đổi sang)`, “Mở” như chân “Lưu vào”, “Đổi…” →
`choose(cửa sổ)`, `failed` khi trang Cài đặt đang mở thì thêm câu lỗi ở thanh thông báo của trang);
`name_changed` → `MainWindow.set_device_name` và `NodeHost.set_node_name`; huy hiệu “Đang ẩn” của thẻ
máy này theo `Node.visible` đọc lúc `started` và `visibility_changed`. `history_cleared` (None: xóa
toàn bộ) của trang và của `PairingController` (theo `device_id`, khi hủy ghép đôi có xóa lịch sử) →
`TransfersController.view.invalidate_history` (gỡ lịch sử đang hiện, nạp lại luồng đang mở; spec B3
mục 9.14). “Mở Cài đặt” của gợi ý khi dán không phải file ở luồng chat
(`ChatView.clipboard_settings_requested(id)`) → mở trang SETTINGS, mục Thiết bị tin cậy, tiêu điểm vào
“Đồng bộ clipboard” của máy đó (`_open_clipboard_settings`). Ngôn ngữ, chế độ màu và màu
nhấn đã lưu (`settings.json`) được áp lúc khởi động (`_saved_settings`: `Settings.load` một lần,
chỉ đọc, lỗi gì cũng về `Settings()`: theo hệ điều hành, màu nhấn mặc định); màn “Bắt đầu” cũng dùng
chủ đề đọc lúc này. Cùng `Settings` đó được đưa cho `GuiApp(saved=...)` (nhớ trạng thái, bên dưới).

**Nhớ trạng thái cửa sổ** (`ui.placement`): `GuiApp` nhận `saved` (`Settings` đọc lúc khởi động; None =
mặc định). Dòng đầu `start()` gọi `placement.restore(window, saved.window)` khi cửa sổ còn ẩn, cả khi
`--background` (trước `tray.show()` và `start_node()`). `current_changed` của danh sách cuộc trò chuyện
(id khác None) cập nhật `_last_conversation`; `start_node` đặt `_restore_conversation` = máy đó trước
`devices.clear()`, rồi `_on_devices` của host hiện tại (chụp và xóa nó; kết quả của host cũ không đụng
tới) sau `devices.reset` chọn lại máy đó bằng `select_device` (không đổi trang, không đổi tiêu điểm; máy
không còn thì giữ hàng 0). `_save_ui_state` lưu qua `NodeHost.call` → `Node.set_ui_preferences` chỉ các
trường khác mốc (giá trị đọc lúc đầu, cập nhật khi lưu xong): `window` (`placement.capture`, None thì
không gửi), `last_conversation`, `tray_hint_shown=True` khi đã báo câu khay; không có gì đổi hay node
không chạy thì không gọi. Gọi ở: ẩn xuống khay, Thoát (ngay sau `_quitting = True`, trước khi ẩn cửa sổ
và `NodeHost.stop()`; `call` và `stop` cùng đi `call_soon_threadsafe` nên lần lưu chạy trước
`Node.close()`), `commitDataRequest` và dòng đầu `shutdown()`; gọi lặp không sao. `on_done` coi mọi kết
quả không phải `BaseException` là thành công (cả None, False) rồi cập nhật mốc; lỗi → WARNING (tên loại
lỗi), giữ mốc nên lần sau gửi lại; không bỏ kết quả khi đang thoát. `on_done` có thể không chạy khi
`exec()` đã trả về, nhưng việc ghi vẫn xảy ra vì `shutdown` `join` thread node. Lưu lúc tắt máy / đăng
xuất là best-effort: không chặn và không trì hoãn việc tắt máy.

**Gửi/nhận file**: `ui.transfers.TransfersController` (`GuiApp.transfers`) giữ luồng chat, hộp
hỏi nhận file và việc gửi; `GuiApp` chỉ báo host mới (`attach`), `started`, `NodeEvent` và
`TransferUpdate` của host hiện tại cho nó. Lời mời nhận file (spec B4 mục 3.6): “Đổi…” của hộp hỏi
và bong bóng (`change_receive_dir_requested`) → `receive_dir_controller.choose(cửa sổ khi đang hiện và
không thu nhỏ, không thì None)` (không lấy hộp hỏi làm cha: hộp `WA_DeleteOnClose` có thể bị xóa khi
hộp chọn còn mở); `always_accept_saved` khi đang ở trang Cài đặt → `settings.refresh()`.

**Thư mục nhận** (`ui.receive_dir.ReceiveDirController`, `GuiApp.receive_dir_controller`; spec B1b):
node chạy với thư mục nhận đã lưu (`ReceiveDirChoice.SAVED`). Host mới → `attach`; `started` →
`on_started` rồi `show_running(tên, thư mục nhận, thư mục đã lưu hỏng)`. `state_changed` → cửa sổ
(`set_receive_dir`, `set_receive_dir_pending`) và `TransfersController.set_receive_dir`,
`set_receive_dir_pending` (hộp hỏi, panel lời mời tắt “Nhận” khi đang đổi); đã ổn thì
`show_receive_dir_error(None)`. “Đổi…” ở
chân “Lưu vào” (`change_receive_dir_requested`) → `choose(cửa sổ)`. `failed` → thanh thông báo của
luồng chat (`ChatView`) và `TransfersController.show_receive_dir_error` (các hộp hỏi đang mở);
UNAVAILABLE và RESERVED kèm nút “Chọn thư mục khác”. Thư mục đã lưu hỏng lúc
`started`: node vẫn chạy (không màn lỗi), dải `unavailable_text` kèm nút “Chọn thư mục nhận”, và
cửa sổ không hiện (chạy nền) thì thêm bóng thoại khay `unavailable_tray_text`. App nhớ câu cuối nó
hiện ở dải (`_receive_dir_notice`); `state_changed` mà thư mục nhận đã ổn (có thư mục nhận, hết
hỏng, không đang đổi) và dải vẫn hiện đúng câu đó thì ẩn dải. Đang thoát thì không hiện dải, không
bóng thoại, bỏ `failed`. Thoát và `shutdown` gọi `close_all` (đóng hộp chọn).

**Chờ ghép đôi** (spec D3, mvp F3, mục 7.5): `_wire_wait_pairing` dựng `ui.wait_pairing.WaitPairingController`
(`GuiApp.wait_pairing`; đăng ký trang WAIT_PAIRING, nối nút “Chờ ghép đôi” của trang “Tìm máy mới”);
host mới → `attach`; địa chỉ đọc được ở `_on_addresses` cũng chuyển cho trang, mở trang thì đọc lại
ngay (`refresh_addresses_requested` → `_refresh_addresses`); `visibility_changed` của Cài đặt → câu
“đang ẩn”; `notice` của ghép đôi → thanh thông báo của trang khi trang mở. “Đang mở” và việc bật/tắt
`accept_pairing` qua `NodeHost.set_wait_pairing_open`: docstring của `ui.wait_pairing`.

**Ghép đôi** (`ui.pairing.PairingController`): ghép đôi máy mới và nhập IP chỉ ở trang “Tìm máy
mới” (trên); `conversations.unpair_requested` (menu “Hủy ghép đôi…”, nút của dải thông báo) → hộp xác
nhận hủy ghép đôi; `devices_changed` (đọc lại `devices()` sau ghép đôi / hủy ghép đôi) →
`devices.reset`. Mỗi host mới
gọi `set_host` (đóng mọi hộp của host cũ); Thoát gọi `close_all`.

**Ghép rồi gửi**: `TransfersController.pair_needed` → `pair_device`; `PairingController.job_done`
(việc ghép chủ động kết thúc mà không PAIRED, hay `pair_device` không bắt đầu được) và `paired`
→ `TransfersController.on_pairing_finished` (từ B2 giao diện không còn đường vào luồng này; gỡ ở
B2c). Nút “Ghép đôi lại” (`repair_requested`) → `pair_device`; không bắt đầu được vì không thấy máy
kia trong mạng (không bận, có host) thì `MainWindow.open_address_entry(repair_offline_text(…))`: mở
trang “Tìm máy mới”, câu ở thanh thông báo của trang, tiêu điểm ở ô “Nhập IP…”, không điền sẵn IP.

**Log ra file** (spec hackathon Q7, mục 9.10): `<config_dir>/logs/teleport.log`, xoay khi đầy
`LOG_MAX_BYTES`, giữ thêm `LOG_BACKUPS` bản cũ; mức WARNING như log ra stderr. Chỉ gắn **sau**
`SingleInstance.acquire` thành công (chỉ một tiến trình ghi và xoay file), gỡ và đóng khi `main` trả
về. Theo mvp N9: chỉ ghi loại lỗi và mã kết quả, không ghi nội dung file hay clipboard; file log
dùng `errorlog.RedactingFormatter` nên traceback không kèm nội dung lỗi. Cùng lúc gắn file log,
`errorlog.install_excepthooks` cài hook ghi ERROR mọi lỗi không bắt được (thread chính, slot Qt,
thread khác), gỡ khi `main` trả về; lỗi lan ra khỏi `main` được ghi trước khi gỡ. Không tạo được
thư mục hay file log thì chỉ ghi WARNING ra stderr (nếu có), app vẫn chạy.

**Một bản mỗi thư mục cấu hình** (`SingleInstance`): bản GUI giữ `<config_dir>/gui.lock` suốt đời
tiến trình (không giữ trước `node.lock` được: trên Windows hai fd cùng tiến trình chặn nhau), rồi
mới `QLocalServer.listen(server_name(config_dir))`. Nhờ giữ `gui.lock` nên được phép
`removeServer` socket cũ (Unix). `acquire` lặp tới `wait` giây: lấy được `gui.lock` (thử trước)
thì mở server; khóa bị giữ mà nối được server thì gửi đúng `b"show\\n"` và trả None (bản kia hiện
cửa sổ); hết hạn → TimeoutError (`main` báo “đang tắt hoặc chưa phản hồi”).
Server coi dữ liệu từ tiến trình khác là không tin cậy: đọc tối đa
`IPC_MAX_BYTES` byte trong `IPC_READ_TIMEOUT_MS`, khớp đúng lệnh thì phát `show_requested`, khác
thì bỏ qua, luôn đóng kết nối; tối đa `IPC_MAX_CONNECTIONS` kết nối cùng lúc. `listen()` lỗi thì
chỉ ghi WARNING (vẫn chỉ một bản nhờ `gui.lock`).

**Địa chỉ máy này** (dòng “Địa chỉ: …” của cửa sổ chính): lúc `started` đọc ngay một lần
`(Node.local_addresses(), Node.port)` bằng `NodeHost.submit` (không chạm Node trên thread Qt), rồi
`address_timer` đọc lại mỗi `ADDRESS_REFRESH_MS` (đổi mạng, đổi Wi-Fi). Lần đọc trước chưa xong thì
lần hẹn sau bỏ qua; kết quả của host cũ hay về lúc đang thoát bị bỏ; lỗi → WARNING (tên loại lỗi),
giữ địa chỉ cũ. Timer dừng khi dựng host mới, `start_failed`, Thoát và `shutdown`.

**GC chỉ trên thread Qt** (`ui.gcguard.GcGuard`): ngay sau khi có `QApplication` (trừ `--selftest`),
`main` tắt GC tự động và thu gom định kỳ trên thread Qt, để đối tượng PySide trong vòng tham chiếu
không bị hủy ở thread node hay thread đĩa; khôi phục sau `shutdown()`.

**Thoát** (`GuiApp.request_quit(confirm=True)`, từ “Thoát” ở khay, phím Thoát, hay đóng cửa sổ khi
không có khay): còn lượt **gửi** chưa kết thúc (`TransfersController.active_sends()`) thì đưa cửa
sổ lên trước và mở hộp hỏi lại không chặn (`quit_box`, objectName `quitConfirmBox`, `open()`;
nút mặc định và Esc là “Không”); đang mở rồi thì chỉ đưa hộp lên trước. Chọn “Thoát” mới thoát.
Không hỏi khi `confirm=False` (Ctrl+C), khi chỉ có lượt nhận dở, hay khi phiên hệ điều hành đang
kết thúc (`commitDataRequest` tới trong `SESSION_END_GRACE_MS` vừa qua — còn chạy sau đó tức là
tắt máy bị hủy —, hay `isSavingSession()`): `commitDataRequest` còn đóng hộp
đang mở, và không bao giờ gọi `QSessionManager.cancel()` (không chặn tắt máy, đăng xuất).
Luồng thoát thật (`_quit_now`): dừng `address_timer`, đóng hộp hỏi lại, đóng server IPC
(`stop_listening`, `gui.lock` giữ tới `shutdown`), đóng các hộp hỏi và hộp chọn file
(`TransfersController.close_all`, `ReceiveDirController.close_all`), ẩn cửa sổ và khay,
`NodeHost.stop()` (không chặn), `stopped` → `quit()`; kèm `QTimer` dự phòng
`close_time_limit() + QUIT_GRACE` giây. Sau `exec()` (trong `finally`): `stop()` lần nữa (không
sao), đóng `SingleInstance`, `join(JOIN_TIMEOUT)`; thread node vẫn sống thì ghi log,
`logging.shutdown()`, `os._exit(1)`.

**Bóng thoại khay**: bấm vào bóng thoại (`Tray.message_clicked(folder)`): `shell.Reveal` (“Đã
nhận…”, gộp ở `ui.notify`) → `shell.show_in_folder(files, root, folder=…)`, Explorer chọn sẵn file vừa
nhận, dự phòng mở thư mục cha bằng seam cấp module `open_url` (mặc định `QDesktopServices.openUrl`, đọc
lúc gọi); `Path` → mở thư mục đó bằng `open_url`; None → đưa cửa sổ chính và mọi hộp đang hiện của
app lên trước. “Mở thư mục” ở chân “Lưu vào” của cửa sổ chính (`open_receive_dir_requested`) mở thư
mục nhận bằng `open_url`; mở không được (cả ở đây lẫn bóng thoại) thì chỉ ghi log, không hiện hộp
nào. Bóng thoại “có yêu cầu
ghép đôi” (qua `PairingController(window_visible=...)`) và “có file đang chờ” (qua
`TransfersController(app_active=...)`) chỉ hiện khi app không được dùng (`GuiApp._app_active()`:
không cửa sổ nào của app đang active).

**Khay** (`ui.tray.Tray`, mvp F9): `set_running(True)` lúc `started`, False khi dựng host mới,
`start_failed` và Thoát (kèm bỏ tạm dừng: tạm dừng nhận chỉ trong phiên). “Gửi file…” → máy chọn
trong menu con (danh sách từ `ConversationModel`, đọc lúc menu sắp hiện) → `bring_to_front`,
`open_conversation`, rồi `TransfersController.pick_and_send` (đường gửi của luồng chat); máy vừa mất
thì chỉ hiện cửa sổ. “Tạm dừng nhận” → `host.call` chạy `pause_receiving` trên thread node; mỗi yêu
cầu có số thứ tự `_pause_seq`: chỉ kết quả của yêu cầu mới nhất được áp lên khay và huy hiệu thẻ
máy này, kết quả cũ chỉ cập nhật `_paused_confirmed`; lỗi thì áp lại giá trị đã xác nhận và ghi
một WARNING. Bóng thoại “vẫn chạy ở khay” (`texts.still_running()`, đang tạm dừng nhận thì
`texts.still_running_paused()`) chỉ hiện lần đầu cửa sổ thu xuống khay trong suốt đời thư mục cấu
hình: đã báo (`Settings.tray_hint_shown`, hay đã báo trong phiên này) thì không báo lại, kể cả ở các
lần mở app sau.

**Clipboard** (mvp F8): `GuiApp` chạy GUI thật (không `make_options`) thì mỗi host mới
có một `ui.clipboard_qt.QtClipboardBackend` (dựng trên thread Qt, cha là `GuiApp`) qua
`NodeOptions.clipboard`; test truyền `clipboard_factory` để bật (mặc định khi có `make_options`: không
đồng bộ clipboard). Backend do factory dựng được dọn khi host của nó phát `stopped`
(`QtClipboardBackend.dispose`; QObject khác: `deleteLater`), nên chạy lại node (“Thử lại”) không để lại
backend cũ. `NodeHost.clipboard_event` của host hiện tại (bỏ khi đang thoát): `RECEIVED` /
`WRITE_FAILED` → `Tray.flash_clipboard` (tên máy qua `texts.peer_label`; khay tự qua `tray_safe`) và
`ChatView.show_clipboard`; `TOO_LARGE` → chỉ `Tray.flash_clipboard`; `SENT` không hiện gì. “Thử lại”
của note (`ChatView.retry_clipboard_requested`) → `host.submit(_retry_clipboard)`: đọc `node.clipboard`
trên thread node (không có → `NOTHING_TO_RETRY`), rồi `ChatView.finish_clipboard_retry` (`NOTHING_TO_RETRY`
→ câu “không còn để chép lại”; lỗi khác chỉ DEBUG và bật lại nút). Không bóng thoại.

Ctrl+C ở cửa sổ dòng lệnh (khi chạy `python -m teleport.ui`): handler SIGINT hẹn luồng Thoát không
hỏi lại (`request_quit(confirm=False)`) bằng `QTimer.singleShot(0, …)` (không gọi thẳng giữa
chừng một slot Qt); một `QTimer` rỗng 200 ms cho Python có dịp chạy handler trong lúc Qt giữ vòng lặp.

**`--selftest`** (cho CI và bản exe): dựng mọi thứ ở trên mà không hiện, không lấy khóa, không mở
mạng; thêm kiểm tài sản đóng gói: lỗi (mã 1) khi thiếu file font điểm nhấn hay Qt từ chối nó
(`fonts.last_error()` là `MISSING`/`REJECTED`; nạp được mà không thấy tên family thì vẫn qua, vì
nền `offscreen` khác nhau giữa các hệ điều hành), khi icon `checkmark_circle` vẽ ra rỗng và khi một
bản dịch có trong `i18n.available_languages()` (khác chuỗi nguồn) không nạp được. Selftest còn dựng
mục “Giao diện” (`ui.appearance.AppearanceSection`) và đổi chủ đề một vòng (tối rồi theo hệ điều
hành) bằng `theme.set_preference`, chạy khay một vòng (`_tray_ok`: các setter trạng thái, một
thông báo clipboard (dấu CLIPBOARD), mỗi `TrayBadge` vẽ ra pixmap 32 px không rỗng, menu con với một
máy giả, đủ bốn mục), dựng `OfferBook`, một `OfferPanel` và một hộp hỏi nhận file có `offerAlways`
(`OfferPrompts.preview`: dựng, không hiện; không quyết định). Khi
chạy từ bản đóng gói (`sys.frozen`) thì kiểm thêm `QFontInfo(font_for(SECTION)).styleName()` là
“Medium” và của TITLE là “Bold” (instance thật của font variable, không đậm giả).

**Danh tính trên Windows** (`APP_USER_MODEL_ID`): chạy từ mã nguồn (`python`/`pythonw`, không
`sys.frozen`), `main` gọi `SetCurrentProcessExplicitAppUserModelID` trước khi dựng `QApplication`;
không có thì Windows gộp cửa sổ và bóng thoại khay vào `python.exe` (icon Python ở taskbar, toast ghi
“Python”). Đặt rồi thì taskbar dùng icon cửa sổ (logo). Không lối tắt nào mang định danh này, nên
đầu toast sẽ hiện nguyên chuỗi định danh; vì vậy `_register_app_user_model_id` (sau khi giữ được
`gui.lock`) ghi `DisplayName` = `texts.APP_NAME` và `IconUri` = `aumid-icon.png` (logo 256 px trong thư mục
cấu hình, ghi nguyên tử khi nội dung khác) vào khóa `AUMID_REGISTRY_KEY` của HKCU, cách
Windows dùng cho app không đóng gói; không cần quyền admin, giá trị đã đúng thì không ghi lại. Bản exe
không đặt và không đăng ký: Windows nhận danh tính theo `Teleport.exe` (icon, FileDescription nhúng
trong exe; lối tắt của bộ cài trỏ đúng exe đó), nên đầu toast là FileDescription. Lỗi → DEBUG, app
vẫn chạy.

Khi `sys.stderr is None` (exe windowed) thì không in gì và không lỗi: argparse tự bỏ qua, log
không có handler ra stderr.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import getpass
import hashlib
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from types import FrameType
from typing import Any, cast

from PySide6.QtCore import QBuffer, QCoreApplication, QEventLoop, QIODevice, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontInfo
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from teleport import paths
from teleport.app import autostart
from teleport.app import node as app_node
from teleport.app.clipboard import ClipboardBackend, ClipboardEvent, ClipOutcome
from teleport.app.devices import DeviceView
from teleport.app.node import NodeEvent
from teleport.app.settings import Settings, WindowGeometry
from teleport.app.transfers import Direction, FileEntry, OfferReceived, TransferKey, TransferUpdate
from teleport.atomic import write_atomic
from teleport.lock import NodeLock, NodeLockedError
from teleport.trust.identity import CERT_FILE, Identity
from teleport.ui import (
    errorlog,
    first_run,
    fonts,
    i18n,
    icons,
    logo,
    placement,
    receive_dir,
    send,
    shell,
    texts,
    theme,
)
from teleport.ui import transfers as ui_transfers
from teleport.ui.appearance import AppearanceSection
from teleport.ui.bridge import NodeHost, NodeOptions, StartError, SubmitJob
from teleport.ui.chat_bubbles import OfferPanel
from teleport.ui.clipboard_qt import QtClipboardBackend
from teleport.ui.conversations import is_online
from teleport.ui.first_run import FirstRunChoice, TextSource
from teleport.ui.gcguard import GcGuard
from teleport.ui.main_window import MainWindow, Page, ViewState
from teleport.ui.offer import OfferBook, OfferPrompts
from teleport.ui.pairing import PairingController, repair_offline_text
from teleport.ui.radar import DeviceListModel
from teleport.ui.receive_dir import ChangeError, ReceiveDirController
from teleport.ui.settings import Section, SettingsController, SettingsPage, autostart_state_hint
from teleport.ui.transfers import TransfersController
from teleport.ui.tray import ClipNotice, ClipNoticeKind, SendTarget, Tray, TrayBadge, make_icon
from teleport.ui.wait_pairing import WaitPairingController
from teleport.ui.widgets import InfoLevel

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

# AppUserModelID khi chạy từ mã nguồn trên Windows (docstring module). Giữ cố định: đổi là ghim taskbar và
# cài đặt thông báo của Windows cho bản chạy từ nguồn mất theo.
APP_USER_MODEL_ID = "NhaCongDong.Teleport"
AUMID_REGISTRY_KEY = rf"Software\Classes\AppUserModelId\{APP_USER_MODEL_ID}"  # trong HKCU
AUMID_ICON_FILE = "aumid-icon.png"
AUMID_ICON_SIZE = 256

GUI_LOCK_FILE = "gui.lock"
SHOW_COMMAND = b"show\n"
IPC_MAX_BYTES = 16
IPC_READ_TIMEOUT_MS = 1000
IPC_MAX_CONNECTIONS = 4
JOIN_TIMEOUT = 5.0  # giây chờ thread node sau `exec()`
QUIT_GRACE = 5.0  # giây cộng thêm `close_time_limit()` cho QTimer dự phòng lúc thoát
LOG_DIR = "logs"
LOG_FILE = "teleport.log"
LOG_MAX_BYTES = 1024 * 1024  # một file log tối đa 1 MiB
LOG_BACKUPS = 1  # giữ thêm một bản cũ: tối đa 2 file
ADDRESS_REFRESH_MS = 10_000  # chu kỳ đọc lại địa chỉ máy này (đọc lúc hẹn, test chỉnh được)
# Sau `commitDataRequest` không hỏi lại khi Thoát trong từng này ms. Phiên kết thúc thật thì tiến trình
# đã bị đóng trước đó; còn chạy tức là tắt máy bị hủy (app khác chặn), nên hỏi lại như thường.
SESSION_END_GRACE_MS = 30_000

# Seam: mở URL (thư mục nhận) bằng ứng dụng mặc định của hệ điều hành; đọc lúc gọi.
open_url: Callable[[QUrl], object] = QDesktopServices.openUrl

_CONNECT_TIMEOUT_MS = 200
_ACK_TIMEOUT_MS = 1500  # client chờ server đọc lệnh rồi đóng kết nối
_ACQUIRE_RETRY_MS = 100
_SIGNAL_POLL_MS = 200

log = logging.getLogger(__name__)


# ---- Một bản mỗi thư mục cấu hình ----------------------------------------------------------


def server_name(config_dir: Path) -> str:
    """Tên `QLocalServer` của thư mục cấu hình: ổn định, không lộ đường dẫn, riêng mỗi người dùng.

    `"teleport-" + sha256(f"{user}\\0{norm}")[:24]`, `norm = normcase(realpath(config_dir))` (Windows:
    không phân biệt hoa thường, bỏ `\\` cuối). `getpass.getuser()` lỗi thì `user = ""`.
    """
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    norm = os.path.normcase(os.path.realpath(os.fspath(config_dir)))
    digest = hashlib.sha256(f"{user}\0{norm}".encode("utf-8", "surrogatepass")).hexdigest()
    return "teleport-" + digest[:24]


def _send_show(name: str) -> bool:
    """Nối tới bản đang chạy và gửi lệnh `show`; True nếu nối được.

    Gửi xong thì chờ server tự đóng kết nối (tối đa `_ACK_TIMEOUT_MS`) trong một vòng sự kiện con,
    không tự ngắt ngay: đóng ống trước khi server kịp đọc thì Windows bỏ mất dữ liệu. Chờ bằng vòng
    sự kiện (không `waitForDisconnected`) để server cùng tiến trình (test) vẫn chạy được.
    """
    sock = QLocalSocket()
    try:
        sock.connectToServer(name)
        if not sock.waitForConnected(_CONNECT_TIMEOUT_MS):
            return False
        loop = QEventLoop()
        sock.disconnected.connect(loop.quit)
        sock.errorOccurred.connect(loop.quit)
        QTimer.singleShot(_ACK_TIMEOUT_MS, loop.quit)
        sock.write(SHOW_COMMAND)
        sock.flush()
        if sock.state() == QLocalSocket.LocalSocketState.ConnectedState:
            loop.exec()
        return True
    finally:
        sock.abort()
        sock.deleteLater()


def _pause(milliseconds: int) -> None:
    """Chờ mà vẫn xử lý sự kiện Qt (không `time.sleep` trên thread Qt)."""
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


class SingleInstance(QObject):
    """Giữ `gui.lock` và server nhận lệnh `show` của bản GUI đang chạy cho một thư mục cấu hình."""

    show_requested = Signal()

    def __init__(self, lock: NodeLock, name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = lock
        self._name = name
        self._server: QLocalServer | None = None
        self._clients: dict[QLocalSocket, bytearray] = {}

    @classmethod
    def acquire(cls, config_dir: Path, wait: float = 3.0) -> SingleInstance | None:
        """Thành bản duy nhất của `config_dir`, hoặc báo bản đang chạy hiện cửa sổ (trả None).

        Mỗi vòng thử lấy `gui.lock` **trước**: được thì `removeServer` + `listen` và trả bản này;
        chỉ khi khóa đang bị giữ mới nối tới server để gửi `show`. Làm ngược lại thì một người dùng
        khác dựng trước pipe/socket cùng tên là đủ làm GUI tưởng đã có bản khác rồi thoát (từ chối
        dịch vụ cục bộ); `gui.lock` nằm trong thư mục cấu hình của chính người dùng nên không giả được.
        Hết `wait` giây mà không được gì → TimeoutError. Không tạo/khóa được `gui.lock` → OSError.
        """
        config_dir = Path(config_dir)
        name = server_name(config_dir)
        deadline = time.monotonic() + max(0.0, wait)
        while True:
            lock = NodeLock(config_dir, GUI_LOCK_FILE)
            try:
                lock.acquire()
            except NodeLockedError:
                pass
            else:
                instance = cls(lock, name)
                instance._listen()
                return instance
            if _send_show(name):
                return None
            if time.monotonic() >= deadline:
                raise TimeoutError("một bản Teleport khác giữ gui.lock nhưng không trả lời")
            _pause(_ACQUIRE_RETRY_MS)

    @property
    def name(self) -> str:
        return self._name

    @property
    def listening(self) -> bool:
        return self._server is not None and self._server.isListening()

    def stop_listening(self) -> None:
        """Đóng server và ngắt các kết nối, vẫn giữ `gui.lock` (đang thoát). Gọi nhiều lần không sao."""
        server, self._server = self._server, None
        if server is not None:
            server.close()
            server.deleteLater()
        for sock in list(self._clients):
            self._drop(sock)

    def close(self) -> None:
        """`stop_listening()` rồi nhả `gui.lock`. Gọi nhiều lần không sao."""
        self.stop_listening()
        self._lock.release()

    def _listen(self) -> None:
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(self._name)  # an toàn: đang giữ gui.lock
        if not server.listen(self._name):
            log.warning("không mở được kênh nhận lệnh từ bản Teleport khác: %s", server.errorString())
            server.deleteLater()
            return
        server.setMaxPendingConnections(IPC_MAX_CONNECTIONS)
        server.newConnection.connect(self._on_new_connection)
        self._server = server

    def _on_new_connection(self) -> None:
        """Nhận kết nối chờ tới khi đủ `IPC_MAX_CONNECTIONS`; còn lại chờ trong hàng của server.

        Hàng chờ của `QLocalServer` cũng giới hạn ở `IPC_MAX_CONNECTIONS` (`setMaxPendingConnections`):
        đầy thì bên nối tới không nối được và thử lại sau, nên kết nối im lặng không chiếm chỗ mãi
        (mỗi kết nối đã nhận bị ngắt sau `IPC_READ_TIMEOUT_MS`).
        """
        server = self._server
        while (
            server is not None and len(self._clients) < IPC_MAX_CONNECTIONS and server.hasPendingConnections()
        ):
            sock = server.nextPendingConnection()
            if sock is None:
                break
            sock.setReadBufferSize(IPC_MAX_BYTES + 1)
            self._clients[sock] = bytearray()
            timer = QTimer(sock)
            timer.setSingleShot(True)
            timer.timeout.connect(functools.partial(self._drop, sock))
            timer.start(IPC_READ_TIMEOUT_MS)
            sock.readyRead.connect(functools.partial(self._on_ready_read, sock, False))
            sock.disconnected.connect(functools.partial(self._on_ready_read, sock, True))
            self._on_ready_read(sock, False)

    def _on_ready_read(self, sock: QLocalSocket, final: bool) -> None:
        buffer = self._clients.get(sock)
        if buffer is None:
            return
        buffer += bytes(sock.read(IPC_MAX_BYTES + 1 - len(buffer)).data())
        if len(buffer) > IPC_MAX_BYTES:
            self._drop(sock)
            return
        if not (final or b"\n" in buffer or len(buffer) == IPC_MAX_BYTES):
            return
        matched = bytes(buffer) == SHOW_COMMAND
        self._drop(sock)
        if matched:
            self.show_requested.emit()

    def _drop(self, sock: QLocalSocket) -> None:
        if self._clients.pop(sock, None) is None:
            return
        sock.abort()
        sock.deleteLater()
        if self._server is not None:
            QTimer.singleShot(0, self._on_new_connection)  # nhận kết nối đang chờ trong hàng


# ---- Ráp các phần --------------------------------------------------------------------------


def quit_confirm_title() -> str:
    """Tiêu đề hộp hỏi lại khi Thoát còn lượt gửi dở."""
    return QCoreApplication.translate("GuiApp", "Thoát Teleport?")


def quit_confirm_text(names: Sequence[str]) -> str:
    """Câu hỏi lại khi Thoát còn lượt gửi dở; `names` đã qua `texts.peer_label`, không rỗng."""
    t = QCoreApplication.translate
    if len(names) == 1:
        return texts.fill(
            t("GuiApp", "Đang gửi file tới {name}. Thoát bây giờ sẽ hủy lượt gửi."), name=names[0]
        )
    return t("GuiApp", "Đang gửi file tới %n máy. Thoát bây giờ sẽ hủy các lượt gửi.", None, len(names))


def quit_cancel_text() -> str:
    """Nút “Không” của hộp hỏi lại khi Thoát (nút mặc định, Esc)."""
    return QCoreApplication.translate("GuiApp", "Không")


async def _read_addresses(node: app_node.Node) -> tuple[tuple[str, ...], int | None]:
    """Chạy trên loop của node: địa chỉ IPv4 của máy này và cổng đang lắng nghe."""
    return (await node.local_addresses(), node.port)


class GuiApp(QObject):
    """Cửa sổ, khay, gửi/nhận file (`transfers`) và node của một tiến trình `teleport-gui`.

    `make_options` (test) dựng `NodeOptions` cho mỗi lần chạy node; mặc định: thư mục nhận đã lưu
    (`ReceiveDirChoice.SAVED`; chưa lưu thì `paths.default_receive_dir()`), mọi địa chỉ, mDNS quảng bá.
    Ở lần chạy đầu (`_first_run`), `start_node` thêm `name`, `save_args=True` và thư mục người dùng
    chọn; `make_options` trả `Path` tường minh mà người dùng không đổi thư mục thì đường dẫn đó cũng
    được lưu (vì `save_args`).
    """

    def __init__(
        self,
        app: QApplication,
        config_dir: Path,
        instance: SingleInstance | None = None,
        *,
        background: bool = False,
        make_options: Callable[[Path], NodeOptions] | None = None,
        saved: Settings | None = None,
        clipboard_factory: Callable[[QObject], ClipboardBackend | None] | None = None,
    ) -> None:
        super().__init__()
        saved = Settings() if saved is None else saved
        self._app = app
        self._config_dir = config_dir
        self._instance = instance
        self._background = background
        self._make_options = make_options or _default_options
        if clipboard_factory is None and make_options is None:
            clipboard_factory = _qt_clipboard  # GUI thật: đồng bộ clipboard (docstring module)
        self._clipboard_factory = clipboard_factory
        self._quitting = False
        # Nhớ trạng thái cửa sổ (docstring module): hình học đã lưu, câu khay đã báo, cuộc trò chuyện
        # gần nhất; `_mark_*` là giá trị đã có trong `settings.json` (chỉ gửi trường khác mốc).
        self._saved_window = saved.window
        self._told_tray = saved.tray_hint_shown
        self._last_conversation = saved.last_conversation
        self._restore_conversation: str | None = None  # máy cần chọn lại ở ảnh chụp `devices()` tới
        self._mark_window: WindowGeometry | None = saved.window
        self._mark_conversation: str | None = saved.last_conversation
        self._mark_tray_hint = saved.tray_hint_shown
        # Lựa chọn ở màn lần chạy đầu, giữ tới `started` (“Thử lại” dùng lại); None: chưa bấm “Bắt đầu”.
        self._first_run: FirstRunChoice | None = None
        self._session_ending = False  # hệ điều hành đang tắt máy / đăng xuất (`commitDataRequest`)
        self._quit_box: QMessageBox | None = None
        self._address_job: SubmitJob | None = None
        self._receive_dir_notice: texts.Text | None = None  # câu cuối app hiện ở dải về thư mục nhận
        self._settings_dir_notice: str | None = None  # câu lỗi thư mục nhận đang ở trang Cài đặt
        self._view_chosen = False  # người dùng đã bấm đổi dạng hiển thị kể từ lần `started` gần nhất
        self.host: NodeHost | None = None
        self._old_hosts: list[NodeHost] = []
        self.window = MainWindow()
        self.tray = Tray(self)
        self.transfers = TransfersController(
            self.window, self.tray, self, app_active=lambda: self._app_active()
        )
        self.receive_dir_controller = ReceiveDirController(self)
        self.pairing = PairingController(
            self,
            notify=lambda _title, text: self.tray.show_message(text),
            window_visible=lambda: self._app_active(),
            message_parent=lambda: self.window,
            device_lookup=lambda device_id: self.window.devices.device(device_id),
        )
        # Tạm dừng nhận (spec D4 mục 4.3, 14.10): số thứ tự yêu cầu gần nhất và giá trị node đã xác nhận.
        self._pause_seq = 0
        self._paused_confirmed = False
        self._quit_timer = QTimer(self)  # dự phòng: `quit()` dù node chưa báo `stopped`
        self._quit_timer.setSingleShot(True)
        self._quit_timer.timeout.connect(self._app.quit)
        self._session_timer = QTimer(self)  # tắt `_session_ending` sau `SESSION_END_GRACE_MS`
        self._session_timer.setSingleShot(True)
        self._session_timer.timeout.connect(self._end_session_grace)
        self.address_timer = QTimer(self)  # đọc lại địa chỉ máy này mỗi `ADDRESS_REFRESH_MS`
        self.address_timer.timeout.connect(self._refresh_addresses)

        self.window.retry_requested.connect(self._on_retry)
        self.window.start_requested.connect(self._on_start_requested)
        self.window.quit_requested.connect(self.request_quit)
        self.window.hidden_to_tray.connect(self._on_hidden_to_tray)
        self.window.open_receive_dir_requested.connect(self._on_open_receive_dir)
        self.window.change_receive_dir_requested.connect(self._choose_receive_dir)
        self.window.change_first_run_dir_requested.connect(self._choose_first_run_dir)
        self.receive_dir_controller.state_changed.connect(self._on_receive_dir_state)
        self.receive_dir_controller.failed.connect(self._on_receive_dir_failed)
        self.receive_dir_controller.initial_selected.connect(self._on_first_run_dir_selected)
        self.tray.open_requested.connect(self.window.bring_to_front)
        self.tray.quit_requested.connect(self.request_quit)
        self.tray.message_clicked.connect(self._on_message_clicked)
        self.tray.set_send_targets_provider(self._send_targets)
        self.tray.send_to_requested.connect(self._on_tray_send)
        self.tray.discover_requested.connect(self._on_tray_discover)
        self.tray.pause_toggled.connect(self._on_pause_toggled)
        self.transfers.view.change_receive_dir_requested.connect(self._choose_receive_dir)
        self.transfers.view.retry_clipboard_requested.connect(self._on_clipboard_retry)
        self.transfers.view.clipboard_settings_requested.connect(self._open_clipboard_settings)
        app.commitDataRequest.connect(self._on_commit_data)
        self.window.conversations.unpair_requested.connect(self._on_unpair_requested)
        self.window.conversations.current_changed.connect(self._on_conversation_changed)
        self.pairing.devices_changed.connect(self._on_devices_changed)
        self.transfers.pair_needed.connect(self._on_pair_needed)
        self.transfers.repair_requested.connect(self._on_repair_requested)
        self.transfers.change_receive_dir_requested.connect(self._choose_receive_dir_for_offer)
        self.transfers.always_accept_saved.connect(self._on_always_accept_saved)
        self.pairing.job_done.connect(self._on_pair_job_done)
        self.pairing.paired.connect(self._on_paired)
        self.pairing.notice.connect(self.transfers.view.show_notice)
        settings_page = SettingsPage(self._device_model(), self.window.pages)
        self.window.add_page(Page.SETTINGS, settings_page)
        settings_page.header.back_requested.connect(self.window.go_back)
        self.settings = SettingsController(
            settings_page,
            config_dir,
            self,
            message_parent=lambda: self.window,
            open_url=lambda url: open_url(url),
            log_files=lambda: log_files(self._config_dir),
        )
        settings_page.unpair_requested.connect(self._on_unpair_requested)
        settings_page.discover_requested.connect(lambda: self.window.open_page(Page.DISCOVER))
        settings_page.open_receive_dir_requested.connect(self._on_open_receive_dir)
        settings_page.change_receive_dir_requested.connect(self._choose_receive_dir)
        settings_page.set_change_available(True)
        self.settings.name_changed.connect(self._on_name_changed)
        self.settings.visibility_changed.connect(self._on_visibility_changed)
        self.settings.history_cleared.connect(self.transfers.view.invalidate_history)
        self.pairing.history_cleared.connect(self.transfers.view.invalidate_history)
        discover = self.window.discover
        discover.pair_requested.connect(self.pairing.pair_device)
        discover.manual_address_entered.connect(self.pairing.pair_address)
        discover.open_device_requested.connect(self._on_open_device)
        discover.view_preference_changed.connect(self._on_view_preference)
        self.pairing.notice.connect(discover.show_notice)
        self._wire_wait_pairing()
        if instance is not None:
            instance.show_requested.connect(self._on_show_requested)

    @property
    def quitting(self) -> bool:
        return self._quitting

    def _wire_wait_pairing(self) -> None:
        """Trang “Chờ ghép đôi” (spec D3; docstring module, “Chờ ghép đôi”)."""
        self.wait_pairing = WaitPairingController(self.window, self, quitting=lambda: self._quitting)
        self.settings.visibility_changed.connect(self.wait_pairing.set_visible)
        self.pairing.notice.connect(self.wait_pairing.show_notice)
        self.wait_pairing.refresh_addresses_requested.connect(self._refresh_addresses)

    def _device_model(self) -> DeviceListModel:
        """Model thiết bị dùng chung cho trang Cài đặt (một chỗ duy nhất; B2 đổi nguồn ở đây)."""
        return self.window.devices

    @property
    def quit_box(self) -> QMessageBox | None:
        """Hộp hỏi lại khi Thoát còn lượt gửi dở, khi đang mở (objectName `quitConfirmBox`)."""
        return self._quit_box

    def start(self) -> None:
        """Hiện khay, chạy node (hoặc hiện màn lần chạy đầu), hiện cửa sổ trừ khi `--background`, có
        khay và node đang khởi động. Hình học đã lưu được áp trước tiên, khi cửa sổ còn ẩn."""
        placement.restore(self.window, self._saved_window)
        self.tray.show()
        self.start_node()
        if (
            not self._background
            or not Tray.is_available()
            or self.window.view_state is not ViewState.STARTING
        ):
            self.window.bring_to_front()

    def start_node(self) -> None:
        """Dựng một `NodeHost` mới (lần đầu, “Bắt đầu” và “Thử lại”).

        Chưa có `device.crt` và người dùng chưa bấm “Bắt đầu” → màn lần chạy đầu, không chạy node.
        Có `_first_run` thì node chạy với lựa chọn đó (docstring module, “Lần chạy đầu”).
        """
        if self._quitting:
            return
        if self.host is not None:
            if self.host.running or self.window.view_state is ViewState.STARTING:
                return  # node đang chạy hay đang khởi động
            self._old_hosts.append(self.host)  # đã lỗi; thread có thể chưa xong, `shutdown` chờ
            self.host = None
        choice = self._first_run
        if choice is None and not self._setup_done():
            self._show_first_run()
            return
        self._stop_addresses()
        self._restore_conversation = self._last_conversation
        self.window.devices.clear()
        options = self._make_options(self._config_dir)
        if choice is not None:
            options = replace(
                options,
                name=choice.name,
                save_args=True,
                receive_dir=choice.receive_dir if choice.receive_dir_chosen else options.receive_dir,
            )
        backend: ClipboardBackend | None = None
        if options.clipboard is None and self._clipboard_factory is not None:
            backend = self._clipboard_factory(self)
            options = replace(options, clipboard=backend)
        host = NodeHost(options, self)
        if isinstance(backend, QtClipboardBackend):  # backend riêng của host này: dọn khi host dừng
            host.stopped.connect(backend.dispose)
        elif isinstance(backend, QObject):
            host.stopped.connect(backend.deleteLater)
        host.started.connect(functools.partial(self._on_started, host))
        host.start_failed.connect(functools.partial(self._on_start_failed, host))
        host.transfer_event.connect(functools.partial(self._on_transfer, host))
        host.node_event.connect(functools.partial(self._on_node_event, host))
        host.clipboard_event.connect(functools.partial(self._on_clipboard_event, host))
        self.host = host
        self._receive_dir_notice = None
        self._settings_dir_notice = None
        self.receive_dir_controller.attach(host)
        self.transfers.attach(host)
        self.pairing.set_host(host)
        self.settings.attach(host)
        self.wait_pairing.attach(host)
        self.window.set_machine_hidden(False)
        self._reset_pause()
        self.window.show_starting()
        host.start()

    def request_quit(self, confirm: bool = True) -> None:
        """Thoát; còn lượt gửi dở và `confirm` thì hỏi lại trước bằng hộp không chặn.

        Không hỏi khi phiên hệ điều hành đang kết thúc (tắt máy, đăng xuất). Đang thoát → bỏ qua.
        """
        if self._quitting:
            return
        if confirm and not self._session_is_ending():
            names = self.transfers.active_sends()
            if names:
                self._confirm_quit(names)
                return
        self._quit_now()

    def _quit_now(self) -> None:
        """Luồng Thoát: dừng node không chặn, `quit()` khi node dừng xong hoặc khi hết hạn dự phòng."""
        if self._quitting:
            return
        self._quitting = True
        self._save_ui_state()  # trước khi ẩn cửa sổ và trước `host.stop()` (FIFO trên loop của node)
        self._stop_addresses()
        self._reset_pause()
        self._close_quit_box()
        if self._instance is not None:
            self._instance.stop_listening()  # bản mở sau không “show” vào app đang tắt
        self.transfers.close_all()
        self.receive_dir_controller.close_all()
        self.pairing.close_all()
        self.settings.close_all()
        self.window.hide()
        self.tray.hide()
        self._quit_timer.start(int((app_node.close_time_limit() + QUIT_GRACE) * 1000))
        hosts = self._live_hosts()
        if not hosts:
            QTimer.singleShot(0, self._app.quit)
            return
        for host in hosts:
            host.stopped.connect(self._quit_when_stopped)
            host.stop()

    def shutdown(self) -> None:
        """Sau `exec()`: dừng node, đóng `SingleInstance`, chờ thread node có hạn; kẹt → `os._exit(1)`."""
        self._save_ui_state()  # trước `host.stop()`
        self._quit_timer.stop()
        self._stop_addresses()
        self._close_quit_box()
        hosts = [h for h in (self.host, *self._old_hosts) if h is not None]
        for host in hosts:
            host.stop()
        self.transfers.close_all()
        self.receive_dir_controller.close_all()
        self.pairing.close_all()
        self.settings.shutdown()
        if self._instance is not None:
            self._instance.stop_listening()
        deadline = time.monotonic() + JOIN_TIMEOUT
        stuck = [h for h in hosts if not h.join(max(0.0, deadline - time.monotonic()))]
        # Nhả `gui.lock` chỉ sau khi thread node đã nhả `node.lock`: bản mở ngay sau đó không gặp M2
        # vì chính bản đang tắt này. Thread kẹt thì `os._exit` nhả cả hai khóa.
        if self._instance is not None:
            self._instance.close()
        self.tray.dispose()
        if stuck:
            log.error("thread node không dừng sau %.0f s, thoát cứng", JOIN_TIMEOUT)
            logging.shutdown()
            os._exit(EXIT_ERROR)

    # ---- Hỏi lại khi Thoát ---------------------------------------------------------------------

    def _session_is_ending(self) -> bool:
        return self._session_ending or self._app.isSavingSession()

    def _confirm_quit(self, names: list[str]) -> None:
        """Mở hộp hỏi lại (không chặn); đang mở rồi thì chỉ đưa nó lên trước."""
        self.window.bring_to_front()
        box = self._quit_box
        if box is not None:
            box.raise_()
            box.activateWindow()
            return
        title = quit_confirm_title()
        box = QMessageBox(self.window)
        box.setObjectName("quitConfirmBox")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(quit_confirm_text(names))
        box.setAccessibleName(title)
        box.addButton(texts.menu_quit(), QMessageBox.ButtonRole.DestructiveRole)
        no_button = box.addButton(quit_cancel_text(), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no_button)
        box.setEscapeButton(no_button)
        box.finished.connect(functools.partial(self._on_quit_box_finished, box))
        self._quit_box = box
        box.open()

    def _on_quit_box_finished(self, box: QMessageBox, _result: int) -> None:
        """Hộp hỏi lại đóng: chỉ khi người dùng chọn “Thoát” trên hộp đang hiện mới thoát."""
        current = self._quit_box is box
        if current:
            self._quit_box = None
        clicked = box.clickedButton()
        box.deleteLater()
        if (
            current
            and clicked is not None
            and box.buttonRole(clicked) == QMessageBox.ButtonRole.DestructiveRole
        ):
            self._quit_now()

    def _close_quit_box(self) -> None:
        box, self._quit_box = self._quit_box, None
        if box is not None:
            box.close()
            box.deleteLater()

    def _on_commit_data(self, _manager: object = None) -> None:
        """Hệ điều hành sắp tắt máy / đăng xuất: không hỏi lại nữa, đóng hộp đang mở.

        Không bao giờ gọi `QSessionManager.cancel()`: Teleport không chặn tắt máy.
        """
        self._session_ending = True
        self._close_quit_box()
        self._save_ui_state()  # best-effort, không chờ
        self._session_timer.start(SESSION_END_GRACE_MS)  # tới lần nữa thì tính lại từ đầu

    def _end_session_grace(self) -> None:
        self._session_ending = False

    # ---- Địa chỉ máy này -----------------------------------------------------------------------

    def _stop_addresses(self) -> None:
        self.address_timer.stop()
        self._address_job = None

    def _refresh_addresses(self) -> None:
        """Đọc `(local_addresses(), port)` qua `submit`; lần trước chưa xong thì bỏ lần này."""
        host = self.host
        if host is None or self._quitting or not host.running:
            return
        job = self._address_job
        if job is not None and not job.done:
            return
        self._address_job = host.submit(_read_addresses, functools.partial(self._on_addresses, host))

    def _on_addresses(
        self, host: NodeHost, result: tuple[tuple[str, ...], int | None] | BaseException
    ) -> None:
        if host is not self.host or self._quitting:
            return
        if isinstance(result, BaseException):
            log.warning("không đọc được địa chỉ của máy này: %s", type(result).__name__)
            return
        addresses, port = result
        self.window.set_addresses(addresses, port)
        self.wait_pairing.set_addresses(addresses, port)

    # ---- Slot ----------------------------------------------------------------------------------

    def _app_active(self) -> bool:
        """App đang được dùng: một cửa sổ của app (cửa sổ chính hay một hộp) đang active."""
        return ui_transfers.default_app_active()

    def _on_message_clicked(self, folder: object) -> None:
        """Bấm bóng thoại khay: `Reveal` thì hiện các file trong thư mục, `Path` thì mở thư mục, không thì
        đưa cửa sổ và các hộp lên trước."""
        if self._quitting:
            return
        if isinstance(folder, shell.Reveal):
            shown = shell.show_in_folder(
                folder.files, folder.root, open_url=lambda url: open_url(url), folder=folder.folder
            )
            if shown is False:
                log.warning("không mở được thư mục nhận")
            return
        if isinstance(folder, Path):
            if open_url(QUrl.fromLocalFile(str(folder))) is False:
                log.warning("không mở được thư mục nhận")
            return
        self.window.bring_to_front()
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                widget.raise_()
                widget.activateWindow()

    def _on_open_receive_dir(self, path: object) -> None:
        """“Mở thư mục” ở chân “Lưu vào”: mở thư mục nhận bằng ứng dụng mặc định; lỗi chỉ ghi log."""
        if self._quitting or not isinstance(path, Path):
            return
        if open_url(QUrl.fromLocalFile(str(path))) is False:
            log.warning("không mở được thư mục nhận")

    # ---- Thư mục nhận --------------------------------------------------------------------------

    def _choose_receive_dir(self) -> None:
        """“Đổi…” ở chân “Lưu vào”, hay nút của dải thông báo: mở hộp chọn thư mục nhận."""
        if not self._quitting:
            self.receive_dir_controller.choose(self.window)

    def _choose_receive_dir_for_offer(self) -> None:
        """“Đổi…” của hộp hỏi nhận file hay bong bóng lời mời: hộp chọn thư mục, cha là cửa sổ chính
        khi đang hiện và không thu nhỏ (không lấy hộp hỏi làm cha: nó có thể bị xóa khi hộp chọn còn mở)."""
        if self._quitting:
            return
        window = self.window
        parent = window if window.isVisible() and not window.isMinimized() else None
        self.receive_dir_controller.choose(parent)

    def _on_always_accept_saved(self, _device_id: str) -> None:
        """Đã lưu “Luôn nhận” cho một máy: trang Cài đặt đang mở thì đọc lại cài đặt theo thiết bị."""
        if self.window.current_page is Page.SETTINGS:
            self.settings.refresh()

    def _on_receive_dir_state(self) -> None:
        """Thư mục nhận / thư mục hỏng / thư mục đang đổi sang đổi: cập nhật cửa sổ và gửi/nhận."""
        c = self.receive_dir_controller
        self.window.set_receive_dir(c.receive_dir, c.unavailable)
        self.settings.page.set_receive_dir(c.receive_dir, c.unavailable, c.pending)
        self.window.set_receive_dir_pending(c.pending)
        self.transfers.set_receive_dir(c.receive_dir)
        self.transfers.set_receive_dir_pending(c.pending)
        # Cùng điều kiện huy hiệu “Không nhận file” của thẻ máy này (`MainWindow._apply_receive_dir`).
        self.tray.set_receiving_unavailable(c.receive_dir is None and c.unavailable is not None)
        if c.unavailable is not None or c.receive_dir is None or c.changing:
            return
        self.transfers.show_receive_dir_error(None)  # đã ổn: gỡ lỗi đổi thư mục ở các hộp hỏi
        # Đã ổn: gỡ câu lỗi thư mục nhận ở trang Cài đặt nếu trang còn hiện đúng câu đó.
        settings_notice, self._settings_dir_notice = self._settings_dir_notice, None
        if settings_notice is not None and self.settings.notice_text() == settings_notice:
            self.settings.page.clear_notice()
        notice = self._receive_dir_notice
        if notice is None:
            return
        # Đã ổn: gỡ câu về thư mục nhận mà app đã hiện, nếu dải chưa bị thông báo khác đè.
        self._receive_dir_notice = None
        if self.transfers.view.notice_text() == texts.resolve(notice):
            self.transfers.view.hide_notice()

    def _on_receive_dir_failed(self, code: str, text: str) -> None:
        """Đổi thư mục nhận không được: câu ở dải thông báo (thư mục không dùng được → nút chọn lại).

        Đang ở màn lần chạy đầu (chọn thư mục dành riêng) thì câu hiện ngay dưới hàng thư mục."""
        if self._quitting:
            return
        if self.window.view_state is ViewState.WELCOME:
            self.window.first_run.set_dir_error(text)
            return
        # Hộp hỏi giữ nguồn chữ (mã + thư mục) để đổi ngôn ngữ thì dịch lại câu lỗi.
        path = self.receive_dir_controller.failed_path
        self.transfers.show_receive_dir_error(functools.partial(receive_dir.change_error_text, code, path))
        if code in (ChangeError.UNAVAILABLE, ChangeError.RESERVED):
            self.transfers.view.show_notice(text, receive_dir.choose_other_text(), self._choose_receive_dir)
        else:
            self.transfers.view.show_notice(text)
        self._receive_dir_notice = text
        if self.window.current_page is Page.SETTINGS:  # người dùng bấm “Đổi…” ở trang Cài đặt
            action = None
            if code in (ChangeError.UNAVAILABLE, ChangeError.RESERVED):
                action = (receive_dir.choose_other_text(), self._choose_receive_dir)
            self.settings.show_notice(InfoLevel.ERROR, text, action=action)
            self._settings_dir_notice = text

    def _show_receive_dir_unavailable(self, path: Path) -> None:
        """Lúc `started`, thư mục nhận đã lưu không mở được: dải thông báo, và bóng thoại khi chạy nền."""
        if self._quitting:
            return

        # Trạng thái kéo dài (tới khi chọn được thư mục): câu dựng bằng hàm để đổi ngôn ngữ thì dịch lại.
        def text() -> str:
            return receive_dir.unavailable_text(path)

        self.transfers.view.show_notice(text, receive_dir.choose_action_text, self._choose_receive_dir)
        self._receive_dir_notice = text
        if not self.window.isVisible():
            self.tray.show_message(receive_dir.unavailable_tray_text())

    # ---- Lần chạy đầu --------------------------------------------------------------------------

    def _show_first_run(self, choice: FirstRunChoice | None = None, dir_error: TextSource = "") -> None:
        """Màn lần chạy đầu với giá trị gợi ý tính lại (docstring module); `choice`: lựa chọn trước."""
        config_dir = self._config_dir
        switch, hint = _first_run_autostart(config_dir)
        self.window.show_welcome(
            suggested_device_name(config_dir),
            _suggested_receive_dir(config_dir),
            autostart=switch,
            autostart_hint=hint,
            choice=choice,
            dir_error=dir_error,
        )

    def _on_start_requested(self, choice: object) -> None:
        """“Bắt đầu” hợp lệ ở màn lần chạy đầu: người dùng đồng ý chạy Teleport với lựa chọn này."""
        if not isinstance(choice, FirstRunChoice) or self._quitting:
            return
        if self.window.view_state is ViewState.WELCOME:
            self._first_run = choice
            self.start_node()

    def _choose_first_run_dir(self) -> None:
        """“Đổi…” ở màn lần chạy đầu: hộp chọn thư mục khi chưa có node."""
        if self._quitting or self.window.view_state is not ViewState.WELCOME:
            return
        self.receive_dir_controller.choose_initial(
            self.window, self.window.first_run.receive_dir, self._config_dir
        )

    def _on_first_run_dir_selected(self, path: object) -> None:
        if isinstance(path, Path) and self.window.view_state is ViewState.WELCOME and not self._quitting:
            self.window.first_run.set_receive_dir(path)

    def _apply_first_run_autostart(self, enabled: bool) -> bool:
        """Áp lựa chọn tự khởi động của lần chạy đầu (thread Qt); True khi **bật** không được.

        Lỗi chỉ ghi tên loại lỗi (mvp N9) và không chặn gì: node đã chạy."""
        config_dir = self._config_dir
        try:
            current = autostart.state(config_dir)
        except Exception as e:  # `autostart` đã ghi WARNING
            log.debug("không đọc được trạng thái khởi động cùng Windows: %s", type(e).__name__)
            current = autostart.AutostartState.OFF
        if enabled:
            if current is autostart.AutostartState.ON:
                return False
            try:
                autostart.enable(config_dir)
            except Exception as e:
                log.warning("không bật được khởi động cùng Windows: %s", type(e).__name__)
                return True
            return False
        if current is autostart.AutostartState.ON:
            try:
                autostart.disable(config_dir)
            except Exception as e:
                log.warning("không tắt được khởi động cùng Windows: %s", type(e).__name__)
        return False

    def _show_autostart_failed(self) -> None:
        if self._quitting:
            return
        self.transfers.view.show_notice(
            first_run.autostart_failed_text(),
            first_run.open_settings_text(),
            self._open_settings_page,
        )

    def _open_settings_page(self) -> None:
        self.window.open_page(Page.SETTINGS)

    def _open_clipboard_settings(self, device_id: str) -> None:
        """“Mở Cài đặt” của gợi ý khi dán không phải file: mục Thiết bị tin cậy, ô “Đồng bộ clipboard”."""
        if self.window.open_page(Page.SETTINGS):
            self.settings.page.show_section(Section.DEVICES, device_id, focus="clipboard")

    def _on_first_run_marked(self, result: object) -> None:
        if self._quitting:
            return
        if isinstance(result, BaseException):
            log.warning("không ghi được đánh dấu lần chạy đầu: %s", type(result).__name__)

    def _setup_done(self) -> bool:
        try:
            return (self._config_dir / CERT_FILE).is_file()
        except OSError:
            return False

    def _live_hosts(self) -> list[NodeHost]:
        return [h for h in (self.host, *self._old_hosts) if h is not None and not h.is_stopped]

    def _quit_when_stopped(self) -> None:
        if not self._live_hosts():
            self._app.quit()

    def _on_started(self, host: NodeHost) -> None:
        if host is not self.host:
            return
        choice, self._first_run = self._first_run, None
        autostart_failed = False
        if choice is not None and choice.autostart is not None and not self._quitting:
            # Trước `settings.on_started`: Cài đặt đối chiếu `settings.autostart` theo registry mới.
            autostart_failed = self._apply_first_run_autostart(choice.autostart)
        controller = self.receive_dir_controller
        controller.on_started(host)
        self.window.show_running(host.node_name, controller.receive_dir, controller.unavailable)
        self.tray.set_receiving_unavailable(
            controller.receive_dir is None and controller.unavailable is not None
        )
        self.tray.set_running(not self._quitting)
        host.call(lambda node: node.devices(), functools.partial(self._on_devices, host))
        self._view_chosen = False
        host.call(lambda node: node.settings.radar_view, functools.partial(self._on_radar_view, host))
        self.transfers.on_started(host)
        if controller.unavailable is not None:
            self._show_receive_dir_unavailable(controller.unavailable)
        elif autostart_failed:
            self._show_autostart_failed()
        self.settings.on_started(host)
        host.call(_mark_first_run_done, self._on_first_run_marked)
        host.call(lambda node: node.visible, functools.partial(self._on_visible_read, host))
        if not self._quitting:
            self._stop_addresses()
            self._refresh_addresses()
            self.address_timer.start(ADDRESS_REFRESH_MS)

    def _on_devices(self, host: NodeHost, result: tuple[DeviceView, ...] | BaseException) -> None:
        """Ảnh chụp `Node.devices()` lúc `started` (sự kiện tới trước đó đã nằm trong ảnh chụp); chọn lại
        cuộc trò chuyện gần nhất nếu máy đó còn trong danh sách."""
        if host is not self.host or self._quitting:
            return  # kết quả của host cũ không lấy mất lần khôi phục của host mới
        wanted, self._restore_conversation = self._restore_conversation, None
        if isinstance(result, BaseException):
            log.warning("không đọc được danh sách thiết bị: %s", type(result).__name__)
            return
        self.window.devices.reset(result)
        if wanted is not None:
            self.window.conversations.select_device(wanted)  # không còn → False, hàng 0 giữ nguyên

    def _on_radar_view(self, host: NodeHost, result: str | BaseException | None) -> None:
        """`radar_view` đã lưu; bỏ nếu host cũ, đang thoát, hay người dùng vừa tự chọn dạng."""
        if host is not self.host or self._quitting:
            return
        if isinstance(result, BaseException):
            log.warning("không đọc được cài đặt dạng hiển thị: %s", type(result).__name__)
            return
        if not self._view_chosen:
            self.window.discover.set_view_preference(result)

    def _on_view_preference(self, value: str) -> None:
        """Người dùng bấm đổi dạng hiển thị: lưu `radar_view` (lỗi thì vẫn giữ trong RAM)."""
        self._view_chosen = True
        host = self.host
        if host is None or self._quitting:
            return
        host.call(lambda node: node.set_ui_preferences(radar_view=value), self._on_view_saved)

    @staticmethod
    def _on_view_saved(result: object) -> None:
        if isinstance(result, BaseException):
            log.warning("không lưu được cài đặt dạng hiển thị: %s", type(result).__name__)

    def _on_visible_read(self, host: NodeHost, result: object) -> None:
        """`Node.visible` lúc `started`: huy hiệu “Đang ẩn” của thẻ máy này."""
        if host is not self.host or self._quitting:
            return
        if isinstance(result, BaseException):
            log.warning("không đọc được chế độ ẩn: %s", type(result).__name__)
            return
        self.window.set_machine_hidden(result is False)

    def _on_visibility_changed(self, visible: bool) -> None:
        """Đổi ẩn/hiện trong Cài đặt xong: huy hiệu “Đang ẩn”."""
        self.window.set_machine_hidden(not visible)

    def _on_name_changed(self, name: str) -> None:
        """Đổi tên trong Cài đặt xong: thẻ máy này và tên host nhớ."""
        self.window.set_device_name(name)
        host = self.host
        if host is not None:
            host.set_node_name(name)

    def _on_open_device(self, device_id: str) -> None:
        """Bấm máy đã ghép đôi ở trang “Tìm máy mới”: về HOME, mở cuộc trò chuyện của máy đó."""
        self.window.open_conversation(device_id)

    def _on_devices_changed(self, views: tuple[DeviceView, ...]) -> None:
        """Danh sách đọc lại sau ghép đôi / hủy ghép đôi (kho tin cậy đổi không phát NodeEvent)."""
        if not self._quitting:
            self.window.devices.reset(views)

    def _on_pair_needed(self, view: DeviceView) -> None:
        """“Ghép rồi gửi”: không bắt đầu được (offline, đang bận) thì bỏ ngay việc chờ gửi."""
        busy = self.pairing.busy  # bận thì `pair_device` tự báo câu “đang bận”
        if not self.pairing.pair_device(view):
            self.transfers.on_pairing_finished(view.device_id, False)
            if not busy:
                self.transfers.view.show_notice(
                    send.not_paired_message(texts.peer_label(view.name, view.device_id))
                )

    def _on_repair_requested(self, view: DeviceView) -> None:
        """Nút “Ghép đôi lại”: không thấy máy kia trong mạng (mDNS bị chặn) thì mời nhập IP ở trang
        “Tìm máy mới”.

        Bận thì `pair_device` tự báo câu “đang bận”; chưa có host thì không làm gì. Không điền sẵn
        IP (địa chỉ cũ có thể đã thuộc máy khác).
        """
        busy = self.pairing.busy
        if self.pairing.pair_device(view) or busy or self.host is None or self._quitting:
            return
        peer = texts.peer_label(view.name, view.device_id)
        self.window.open_address_entry(functools.partial(repair_offline_text, peer))

    def _on_pair_job_done(self, device_id: str | None, paired: bool) -> None:
        """Việc ghép chủ động kết thúc; PAIRED thì chờ `paired` (sau khi đã đọc lại `devices()`)."""
        if not paired:
            self.transfers.on_pairing_finished(device_id, False)

    def _on_paired(self, device_id: str) -> None:
        self.transfers.on_pairing_finished(device_id, True)

    def _on_unpair_requested(self, device_id: str) -> None:
        view = self.window.devices.device(device_id)
        self.pairing.request_unpair(device_id, None if view is None else view.name)

    def _on_node_event(self, host: NodeHost, event: NodeEvent) -> None:
        if host is self.host and not self._quitting:
            self.window.devices.apply(event)
            self.transfers.on_node_event(event)

    def _on_start_failed(self, host: NodeHost, code: str, detail: str) -> None:
        if host is not self.host:
            return
        self._stop_addresses()
        self._reset_pause()
        if code != StartError.LOCKED:
            log.warning("node không khởi động được: %s", code)
        choice = self._first_run
        if code == StartError.RECEIVE_DIR and choice is not None and choice.receive_dir_chosen:
            # Lần chạy đầu, thư mục người dùng vừa chọn không mở được: sửa ngay trên màn đó.
            self._show_first_run(
                choice,
                functools.partial(receive_dir.change_error_text, ChangeError.UNAVAILABLE, choice.receive_dir),
            )
            if not self._quitting:
                self.window.bring_to_front()
            return
        self.window.show_error(code, detail)
        if not self._quitting:
            self.window.bring_to_front()  # kể cả khi `--background`: người dùng phải biết

    def _on_transfer(self, host: NodeHost, update: TransferUpdate) -> None:
        if host is self.host and not self._quitting:
            self.transfers.on_transfer(update)

    def _on_retry(self) -> None:
        if self.window.view_state is ViewState.ERROR:
            self.start_node()

    def _on_show_requested(self) -> None:
        """Mở Teleport lần nữa: hiện cửa sổ; đang lỗi thì thử chạy lại (màn lần chạy đầu vẫn chờ bấm)."""
        if self._quitting:
            return
        self.window.bring_to_front()
        if self.window.view_state is ViewState.ERROR:
            self.start_node()

    def _on_hidden_to_tray(self) -> None:
        """Thu cửa sổ xuống khay: chưa từng báo thì bóng thoại “vẫn chạy ở khay” (đang tạm dừng nhận thì
        câu riêng), rồi lưu trạng thái cửa sổ."""
        if not self._told_tray:
            self._told_tray = True
            if self._paused_confirmed:
                self.tray.show_message(texts.still_running_paused())
            else:
                self.tray.show_message(texts.still_running())
        self._save_ui_state()

    # ---- Nhớ trạng thái cửa sổ -----------------------------------------------------------------

    def _on_conversation_changed(self, device_id: object) -> None:
        if isinstance(device_id, str):
            self._last_conversation = device_id

    def _save_ui_state(self) -> None:
        """Lưu các trường nhớ trạng thái khác mốc qua node; node không chạy hay không có gì đổi → thôi."""
        host = self.host
        if host is None or not host.running:
            return
        changes: dict[str, Any] = {}
        window = placement.capture(self.window, fallback=self._mark_window)
        if window is not None and window != self._mark_window:
            changes["window"] = window
        conversation = self._last_conversation
        if conversation is not None and conversation != self._mark_conversation:
            changes["last_conversation"] = conversation
        if self._told_tray and not self._mark_tray_hint:
            changes["tray_hint_shown"] = True
        if not changes:
            return
        host.call(
            lambda node: node.set_ui_preferences(**changes),
            functools.partial(self._on_ui_state_saved, changes),
        )

    def _on_ui_state_saved(self, changes: dict[str, Any], result: object) -> None:
        """Mọi kết quả không phải `BaseException` là đã lưu (cả None, False): cập nhật mốc."""
        if isinstance(result, BaseException):
            log.warning("không lưu được trạng thái cửa sổ: %s", type(result).__name__)
            return
        if "window" in changes:
            self._mark_window = changes["window"]
        if "last_conversation" in changes:
            self._mark_conversation = changes["last_conversation"]
        if "tray_hint_shown" in changes:
            self._mark_tray_hint = True

    # ---- Clipboard (mvp F8) ------------------------------------------------------------------

    def _peer_label(self, device_id: str) -> str:
        view = self.window.devices.device(device_id)
        return texts.peer_label(None if view is None else view.name, device_id)

    def _on_clipboard_event(self, host: NodeHost, event: object) -> None:
        """Sự kiện của `app.clipboard` (đã về thread Qt): khay và luồng chat (docstring module)."""
        if host is not self.host or self._quitting or not isinstance(event, ClipboardEvent):
            return
        outcome = event.outcome
        if outcome is ClipOutcome.TOO_LARGE:
            self.tray.flash_clipboard(ClipNotice(ClipNoticeKind.TOO_LARGE))
            return
        if outcome not in (ClipOutcome.RECEIVED, ClipOutcome.WRITE_FAILED) or event.device_id is None:
            return
        ok = outcome is ClipOutcome.RECEIVED
        device_id = event.device_id
        kind = ClipNoticeKind.RECEIVED if ok else ClipNoticeKind.WRITE_FAILED
        self.tray.flash_clipboard(ClipNotice(kind, self._peer_label(device_id)))
        self.transfers.view.show_clipboard(
            device_id,
            ok=ok,
            kind=event.kind,
            size=event.size,
            preview=event.preview,
            image_size=event.image_size,
        )

    def _on_clipboard_retry(self, device_id: str) -> None:
        """“Thử lại” của note clipboard: ghi lại clip lỗi gần nhất của máy đó trên thread node."""
        host = self.host
        if host is None or self._quitting or not host.running:
            self.transfers.view.finish_clipboard_retry(device_id, available=True)
            return
        host.submit(
            functools.partial(_retry_clipboard, device_id=device_id),
            functools.partial(self._on_clipboard_retry_done, host, device_id),
        )

    def _on_clipboard_retry_done(self, host: NodeHost, device_id: str, result: object) -> None:
        if host is not self.host or self._quitting:
            return
        if isinstance(result, BaseException):
            log.debug("không thử lại được việc chép clipboard: %s", type(result).__name__)
        available = result is not ClipOutcome.NOTHING_TO_RETRY
        self.transfers.view.finish_clipboard_retry(device_id, available=available)

    # ---- Khay: Gửi file…, Tạm dừng nhận ---------------------------------------------------------

    def _send_targets(self) -> list[SendTarget]:
        """Máy cho menu con “Gửi file…” của khay: thứ tự danh sách cuộc trò chuyện (chỉ máy đã ghép đôi)."""
        return [
            SendTarget(view.device_id, texts.peer_label(view.name, view.device_id), is_online(view))
            for view in self.window.conversations.model.devices()
        ]

    def _on_tray_send(self, device_id: str) -> None:
        """Chọn một máy ở “Gửi file…” của khay: hiện cửa sổ, mở cuộc trò chuyện, mở hộp chọn file."""
        if self._quitting:
            return
        self.window.bring_to_front()
        if self.window.open_conversation(device_id):  # False: máy vừa bị hủy ghép đôi
            self.transfers.pick_and_send(device_id)

    def _on_tray_discover(self) -> None:
        """“Tìm máy mới…” của khay (chưa ghép đôi máy nào): hiện cửa sổ, mở trang DISCOVER."""
        if self._quitting:
            return
        self.window.bring_to_front()
        self.window.open_page(Page.DISCOVER)

    def _on_pause_toggled(self, paused: bool) -> None:
        """Người dùng bấm “Tạm dừng nhận”: đổi qua node; chưa có node đang chạy thì trả dấu chọn về cũ."""
        host = self.host
        if host is None or self._quitting or not host.running:
            self.tray.set_receiving_paused(self._paused_confirmed)
            return
        self._pause_seq += 1
        seq = self._pause_seq
        host.call(
            lambda node: _set_receiving_paused(node, paused),
            functools.partial(self._on_pause_done, host, seq),
        )

    def _on_pause_done(self, host: NodeHost, seq: int, result: object) -> None:
        """Node trả việc tạm dừng nhận: chỉ yêu cầu mới nhất được áp vào khay và huy hiệu."""
        if host is not self.host or self._quitting:
            return
        latest = seq == self._pause_seq
        if isinstance(result, bool):
            self._paused_confirmed = result
            if latest:
                self._apply_paused(result)
            return
        if isinstance(result, BaseException):
            log.warning("không đổi được việc tạm dừng nhận: %s", type(result).__name__)
        if latest:
            self._apply_paused(self._paused_confirmed)

    def _apply_paused(self, paused: bool) -> None:
        self.tray.set_receiving_paused(paused)
        self.window.set_receiving_paused(paused)

    def _reset_pause(self) -> None:
        """Host mới, `start_failed`, Thoát: node mới nhận lại (tạm dừng chỉ trong phiên); khay chưa chạy."""
        self._pause_seq += 1  # bỏ kết quả của yêu cầu đang chờ
        self._paused_confirmed = False
        self._apply_paused(False)
        self.tray.set_running(False)


def log_files(config_dir: Path) -> list[Path]:
    """File log để xuất, bản cũ (đã xoay) trước: `teleport.log.1`, `teleport.log`."""
    directory = config_dir / LOG_DIR
    return [directory / f"{LOG_FILE}.{n}" for n in range(LOG_BACKUPS, 0, -1)] + [directory / LOG_FILE]


def _saved_settings(config_dir: Path) -> Settings:
    """`settings.json` đọc một lần lúc khởi động, chỉ đọc; lỗi gì cũng `Settings()` (mặc định)."""
    try:
        return Settings.load(config_dir)
    except Exception as e:
        log.debug("không đọc được cài đặt đã lưu: %s", type(e).__name__)
        return Settings()


def _default_options(config_dir: Path) -> NodeOptions:
    """Mặc định: thư mục nhận đã lưu (`ReceiveDirChoice.SAVED`), mọi địa chỉ, mDNS quảng bá."""
    return NodeOptions(config_dir=config_dir)


class _NoIdentityYet:
    """Đứng thay `Identity` khi chưa có danh tính: mã máy chưa biết."""

    device_id = "????"


# Tên `app.node.default_device_name` trả khi hostname không dùng được và chưa có mã máy.
_FALLBACK_NAME = f"Teleport-{_NoIdentityYet.device_id[:4]}"


def planned_device_name() -> str:
    """Tên node sẽ dùng khi `Node.start` tạo danh tính: `app.node.default_device_name`.

    Hostname dùng được (gần như luôn vậy) thì đúng là tên đó; không thì app dùng `Teleport-<4 ký tự
    đầu mã máy>`, mà mã máy chưa có nên hiện `Teleport-????`. Không I/O đĩa hay mạng.

    Chạy trên thread Qt, nên hostname lấy bằng `socket.gethostname()` (`app.node._hostname`), không qua
    `platform.uname()` (truy vấn WMI qua COM trên Windows, docstring của `_hostname`).
    """
    return app_node.default_device_name(cast(Identity, _NoIdentityYet()))


def suggested_device_name(config_dir: Path) -> str:
    """Tên gợi ý ở màn lần chạy đầu: tên đã lưu (`settings.json`, chỉ đọc), không thì
    `planned_device_name()`; tên dự phòng `Teleport-????` thì "" (người dùng phải gõ tên)."""
    try:
        saved = Settings.load(config_dir).name
    except Exception as e:
        log.debug("không đọc được tên đã lưu: %s", type(e).__name__)
        saved = None
    if saved:
        return saved
    name = planned_device_name()
    return "" if name == _FALLBACK_NAME else name


def _suggested_receive_dir(config_dir: Path) -> Path:
    """Thư mục nhận gợi ý: thư mục đã lưu (chỉ đọc), không thì `paths.default_receive_dir()` (không tạo)."""
    try:
        saved = Settings.load(config_dir).receive_dir
    except Exception as e:
        log.debug("không đọc được thư mục nhận đã lưu: %s", type(e).__name__)
        saved = None
    return Path(saved) if saved else paths.default_receive_dir()


def _first_run_autostart(config_dir: Path) -> tuple[bool | None, TextSource]:
    """(trạng thái ban đầu của công tắc, câu trạng thái) ở màn lần chạy đầu; None: ẩn hàng (spec D1 Q7)."""
    try:
        if not autostart.supported():
            return None, ""
        state = autostart.state(config_dir)
    except autostart.AutostartUnsupported:
        return None, ""
    except Exception as e:  # đọc lỗi: bật sẵn, không câu thêm (Cài đặt sẽ báo)
        log.debug("không đọc được trạng thái khởi động cùng Windows: %s", type(e).__name__)
        return True, ""
    if state is autostart.AutostartState.UNSUPPORTED:
        return None, ""
    if state in (autostart.AutostartState.OTHER, autostart.AutostartState.BLOCKED):
        return False, functools.partial(autostart_state_hint, state)
    return True, ""


def _set_receiving_paused(node: app_node.Node, paused: bool) -> bool:
    """Thread node: tạm dừng (True) hay nhận lại (False) `offer` mới; trả giá trị node đang giữ."""
    node.transfers.pause_receiving(paused)
    return node.transfers.receiving_paused


def _qt_clipboard(parent: QObject) -> ClipboardBackend:
    """Backend clipboard của GUI thật (thread Qt)."""
    return QtClipboardBackend(parent)


async def _retry_clipboard(node: app_node.Node, *, device_id: str) -> ClipOutcome:
    """Thread node: “Thử lại” ghi clipboard; node không đồng bộ clipboard → `NOTHING_TO_RETRY`."""
    sync = node.clipboard
    if sync is None:
        return ClipOutcome.NOTHING_TO_RETRY
    return await sync.retry_write(device_id)


def _mark_first_run_done(node: app_node.Node) -> bool:
    """Thread node: ghi `first_run_done=True` khi còn False; True nếu vừa ghi."""
    if node.settings.first_run_done:
        return False
    node.set_ui_preferences(first_run_done=True)
    return True


# ---- main ----------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="teleport-gui", description="Teleport: gửi file trong mạng LAN.")
    parser.add_argument(
        "--config-dir",
        metavar="D",
        help="thư mục cấu hình (mặc định: TELEPORT_HOME hoặc thư mục của hệ điều hành)",
    )
    parser.add_argument(
        "--background", action="store_true", help="chỉ hiện ở khay hệ thống (khi khởi động cùng máy)"
    )
    parser.add_argument(
        "--selftest", action="store_true", help="dựng giao diện rồi thoát (kiểm tra bản build)"
    )
    return parser


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _setup_logging() -> None:
    if sys.stderr is not None and not logging.getLogger().handlers:
        logging.basicConfig(level=logging.WARNING, format=_LOG_FORMAT)


def _attach_file_log(config_dir: Path) -> logging.Handler | None:
    """Gắn log ra `<config_dir>/logs/teleport.log` (xoay 2 file) vào logger gốc; lỗi → None.

    Chỉ gọi khi đã là bản duy nhất của `config_dir` (giữ `gui.lock`). Mở file lúc ghi dòng đầu tiên
    (`delay=True`), nên chạy bình thường không có lỗi thì không tạo file.
    """
    try:
        directory = config_dir / LOG_DIR
        directory.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            directory / LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUPS,
            encoding="utf-8",
            delay=True,
        )
    except OSError as e:
        log.warning("không mở được file log (%s)", type(e).__name__)
        return None
    handler.setLevel(logging.WARNING)
    handler.setFormatter(errorlog.RedactingFormatter(_LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    return handler


def _detach_file_log(handler: logging.Handler | None) -> None:
    if handler is not None:
        logging.getLogger().removeHandler(handler)
        handler.close()


def _set_app_user_model_id() -> None:
    """Đặt `APP_USER_MODEL_ID` (Windows, không phải bản exe; xem docstring module). Không ném lỗi."""
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return
    import ctypes

    try:
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception as e:  # thiếu hàm (Windows quá cũ) hay ctypes lỗi
        log.debug("không đặt được AppUserModelID: %s", type(e).__name__)
        return
    if result != 0:  # HRESULT khác S_OK
        log.debug("SetCurrentProcessExplicitAppUserModelID trả 0x%08x", result & 0xFFFFFFFF)


def _register_app_user_model_id(config_dir: Path) -> None:
    """Đăng ký tên hiển thị và icon cho `APP_USER_MODEL_ID` ở HKCU (docstring module). Không ném lỗi."""
    if sys.platform != "win32":
        return
    if getattr(sys, "frozen", False):
        return
    import winreg

    icon = config_dir / AUMID_ICON_FILE
    try:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not logo.pixmap(AUMID_ICON_SIZE).save(buffer, "PNG"):
            raise OSError(f"không vẽ được {AUMID_ICON_FILE}")
        png = bytes(buffer.data().data())
        try:
            same = icon.read_bytes() == png
        except FileNotFoundError:
            same = False
        if not same:
            write_atomic(icon, png)  # Windows có thể đọc icon bất cứ lúc nào
        access = winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, AUMID_REGISTRY_KEY, 0, access) as key:
            for name, value in (("DisplayName", texts.APP_NAME), ("IconUri", str(icon))):
                try:
                    current = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    current = None
                if current != (value, winreg.REG_SZ):
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    except OSError as e:
        log.debug("không đăng ký được tên cho AppUserModelID: %s", type(e).__name__)


def _application() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return cast(QApplication, existing)
    return QApplication([sys.argv[0] if sys.argv and sys.argv[0] else "teleport-gui"])


def _assets_ok() -> bool:
    """Phần tài sản của `--selftest`: font điểm nhấn và một icon (xem docstring module)."""
    fonts.install()
    error = fonts.last_error()
    if error in (fonts.MISSING, fonts.REJECTED):
        log.error("selftest: font điểm nhấn lỗi (%s)", error)
        return False
    if getattr(sys, "frozen", False):
        weights = {theme.TextStyle.SECTION: "Medium", theme.TextStyle.TITLE: "Bold"}
        for style, expected in weights.items():
            actual = QFontInfo(theme.font_for(style)).styleName()
            if actual != expected:
                log.error("selftest: %s là %r, cần %r", style.name, actual, expected)
                return False
    if icons.pixmap("checkmark_circle", 20, theme.tokens(False).success).isNull():
        log.error("selftest: không vẽ được icon")
        return False
    for code in i18n.available_languages():
        if code != i18n.SOURCE_LANGUAGE and not i18n.loadable(code):
            log.error("selftest: không nạp được bản dịch %s", code)
            return False
    return True


def _offer_selftest() -> bool:
    """Phần lời mời nhận file của `--selftest`: `OfferBook`, `OfferPanel`, một hộp hỏi có ô “Luôn
    nhận”; đóng hết, không quyết định."""
    key = TransferKey("0" * 64, Direction.RECEIVE, "0" * 32)
    item = OfferReceived(key, "Teleport", (FileEntry("a.txt", 1, 0),), ("a.txt",), 1, False)
    book = OfferBook()
    prompts = OfferPrompts(book, Path("Teleport"))
    answered: list[object] = []
    book.answered.connect(lambda *args: answered.append(args))
    if not book.add(item):
        return False
    entry = book.entry(key)
    panel = OfferPanel()
    if entry is None:
        return False
    panel.set_entry(entry, Path("Teleport"), None)
    box = prompts.preview(key)  # dựng, không hiện
    ok = box is not None and box.findChild(QWidget, "offerAlways") is not None
    ok = ok and len(panel.focus_widgets()) == 4
    book.clear()
    if box is not None:
        box.deleteLater()
    panel.deleteLater()
    prompts.deleteLater()
    book.deleteLater()
    return ok and not answered and not prompts.keys()


def _tray_ok(tray: Tray) -> bool:
    """Phần khay của `--selftest` (spec D4 mục 14.17): một vòng setter, mỗi dấu vẽ ra được, menu con."""
    tray.set_running(True)
    tray.set_activity(2)
    tray.set_receiving_paused(True)
    tray.set_receiving_unavailable(True)
    tray.set_receiving_unavailable(False)
    tray.set_receiving_paused(False)
    tray.set_activity(0)
    tray.flash_clipboard(ClipNotice(ClipNoticeKind.RECEIVED, "Teleport"))
    if tray.badge is not TrayBadge.CLIPBOARD:
        log.error("selftest: khay không hiện dấu clipboard")
        return False
    tray.set_running(False)
    for badge in TrayBadge:
        if make_icon(badge).pixmap(32).isNull():
            log.error("selftest: không vẽ được biểu tượng khay %s", badge.value)
            return False
    tray.set_send_targets_provider(lambda: [SendTarget("selftest", "Teleport", False)])
    tray.menu.aboutToShow.emit()
    if len(tray.send_menu.actions()) != 1 or len(tray.actions()) != 4:
        log.error("selftest: menu khay sai")
        return False
    return True


def _selftest(app: QApplication) -> int:
    """Kiểm tài sản, dựng i18n, theme, cửa sổ, khay, luồng chat mà không hiện; không khóa, không mạng."""
    try:
        i18n.install(app)
        if not _assets_ok():
            return EXIT_ERROR
        theme.apply(app)
        AppearanceSection().deleteLater()
        theme.set_preference(app, theme.Mode.DARK, None)
        theme.set_preference(app, theme.Mode.SYSTEM, None)
        window = MainWindow()
        tray = Tray()
        window.show_welcome(planned_device_name())
        window.show_welcome("Teleport", Path("Teleport"), autostart=True)  # form có công tắc
        window.show_starting()
        window.show_running("Teleport", Path("Teleport"))
        window.show_running("Teleport", None, Path("Teleport"))
        window.devices.reset(())
        for code in StartError:
            window.show_error(code.value, "")
        settings_page = SettingsPage(window.devices, window.pages)
        window.add_page(Page.SETTINGS, settings_page)
        settings_page.set_receive_dir(Path("Teleport"))
        transfers = TransfersController(window, tray)
        transfers.attach(None)
        controller = ReceiveDirController()
        controller.attach(None)
        transfers.view.show_notice(receive_dir.unavailable_text(Path("Teleport")))
        transfers.view.hide_notice()
        if not _tray_ok(tray):
            return EXIT_ERROR
        if (
            len(tray.actions()) != 4
            or transfers.offers.keys()
            or transfers.view.rows()
            or controller.choose(window)
            or not _offer_selftest()
        ):
            return EXIT_ERROR
        app.processEvents()
        tray.dispose()
        window.deleteLater()
        app.processEvents()
        return EXIT_OK
    except Exception:
        log.exception("selftest lỗi")
        return EXIT_ERROR


def _error_box(head: str, hints: list[str]) -> None:
    """Hộp báo lỗi lúc khởi động (trước khi có cửa sổ chính): không cha, chữ thuần."""
    box = QMessageBox(QMessageBox.Icon.Critical, texts.APP_NAME, "\n\n".join([head, *hints]))
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.exec()


def _install_sigint(controller: GuiApp) -> Callable[[], None]:
    """Ctrl+C → luồng Thoát. Trả hàm khôi phục handler cũ."""
    if threading.current_thread() is not threading.main_thread():
        return lambda: None
    previous = signal.getsignal(signal.SIGINT)

    def handler(signum: int, frame: FrameType | None) -> None:
        QTimer.singleShot(0, functools.partial(controller.request_quit, confirm=False))

    try:
        signal.signal(signal.SIGINT, handler)
    except (ValueError, OSError):
        return lambda: None
    poll = QTimer(controller)
    poll.timeout.connect(lambda: None)  # cho Python có dịp chạy handler tín hiệu
    poll.start(_SIGNAL_POLL_MS)

    def restore() -> None:
        poll.stop()
        with contextlib.suppress(ValueError, OSError, TypeError):
            signal.signal(signal.SIGINT, previous)

    return restore


def main(argv: list[str] | None = None) -> int:
    """`teleport-gui`: trả mã thoát (0 bình thường, 1 lỗi, 2 sai tham số)."""
    _setup_logging()
    raw = list(sys.argv[1:] if argv is None else argv)
    try:
        args = _parser().parse_args(raw)
    except SystemExit as e:  # argparse: sai tham số (2) hoặc --help (0)
        return e.code if isinstance(e.code, int) else EXIT_USAGE
    config_dir = Path(os.path.abspath(args.config_dir if args.config_dir else paths.config_dir()))

    _set_app_user_model_id()  # trước khi có cửa sổ nào (taskbar đọc lúc cửa sổ hiện)
    app = _application()
    # Không đặt applicationDisplayName: Qt sẽ nối “ - ZCL Teleport” vào tiêu đề mọi hộp thoại.
    app.setApplicationName(texts.APP_NAME)
    app.setWindowIcon(make_icon())
    app.setQuitOnLastWindowClosed(False)
    if args.selftest:
        return _selftest(app)

    # GC vòng tham chiếu chỉ chạy trên thread Qt (`ui.gcguard`): bật trước khi có node, `SingleInstance`
    # và widget; tắt sau `controller.shutdown()` (đã `join` thread node).
    gc_guard = GcGuard()
    gc_guard.start()
    try:
        return _run(app, args, config_dir)
    finally:
        gc_guard.stop()


def _run(app: QApplication, args: argparse.Namespace, config_dir: Path) -> int:
    """Phần của `main` sau khi có `QApplication` (ngoài `--selftest`), chạy trong `GcGuard`."""
    saved = _saved_settings(config_dir)
    i18n.install(app, saved.language)
    fonts.install()  # lỗi thì `theme.font_for` rơi về font hệ thống
    theme.set_preference(app, theme.mode_from_setting(saved.theme), saved.accent)
    try:
        instance = SingleInstance.acquire(config_dir)
    except TimeoutError:  # trước OSError: TimeoutError là lớp con của OSError
        log.error("một bản Teleport khác đang chạy với %s nhưng không trả lời", config_dir)
        _error_box(*texts.not_responding())
        return EXIT_ERROR
    except OSError as e:
        _error_box(*texts.config_dir_unusable_at_launch(f"{config_dir}\n{e.strerror or e}"))
        return EXIT_ERROR
    if instance is None:
        return EXIT_OK  # bản đang chạy đã hiện cửa sổ

    file_log = _attach_file_log(config_dir)  # sau `acquire`: chỉ bản duy nhất ghi và xoay file
    _register_app_user_model_id(config_dir)  # cũng chỉ bản duy nhất, trước bóng thoại đầu tiên
    restore_excepthooks = errorlog.install_excepthooks()
    try:
        controller = GuiApp(app, config_dir, instance, background=args.background, saved=saved)
        restore_sigint = _install_sigint(controller)
        try:
            controller.start()
            app.exec()
        finally:
            restore_sigint()
            controller.shutdown()
    except Exception as e:  # ghi trước khi gỡ hook và file log; lỗi vẫn lan ra như cũ
        errorlog.log_uncaught(type(e), e, e.__traceback__)
        raise
    finally:
        restore_excepthooks()
        _detach_file_log(file_log)
    return EXIT_OK
