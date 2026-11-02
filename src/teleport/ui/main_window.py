"""Cửa sổ chính: trạng thái của node, màn lần chạy đầu, khung hai cột (spec B1) và khung trang (spec A3).

Bốn trạng thái (`ViewState`); trang HOME có `home_stack` chọn giữa khối căn giữa `start_view`
(`home.StartPanel`: WELCOME, STARTING, ERROR) và khung hai cột `shell` (RUNNING). Mọi đường vào
trạng thái đi qua `retranslate()`, nơi chọn `home_stack` và ẩn/hiện từng phần.

- WELCOME: màn lần chạy đầu khi máy chưa có danh tính (mvp F1, spec D1): form `first_run`
  (`ui.first_run.FirstRunForm`, trong `start_view`: tên thiết bị kèm câu F1, thư mục nhận, khởi động
  cùng Windows, câu đồng ý) và nút chính “Bắt đầu”; dòng trạng thái, chi tiết, gợi ý ẩn. “Bắt đầu” hay
  Enter trong ô tên → `first_run.validate()`; hợp lệ thì phát `start_requested(FirstRunChoice)`, sai
  thì lỗi hiện dưới ô và không phát gì. “Đổi…” → `change_first_run_dir_requested`. Chưa bấm thì
  `ui.app` không chạy node, không quảng bá gì. `show_welcome(tên gợi ý, thư mục gợi ý, autostart=…,
  autostart_hint=…, choice=…, dir_error=…)` đặt giá trị gợi ý (`receive_dir=None` → thư mục mặc
  định), hiện lại lựa chọn trước (`choice`) và lỗi thư mục (`dir_error`).
- STARTING: “Đang khởi động…” kèm thanh bận mảnh (`starting_bar`), không có nút.
- RUNNING: khung hai cột (dưới đây). Không còn dòng chữ trạng thái: tên máy, địa chỉ, huy hiệu nằm ở
  `machine_card`, thư mục nhận ở `save_bar`.
- ERROR: icon lỗi (`status_icon`, màu `danger`, trang trí), “Không khởi động được”, câu lỗi
  (`texts.start_error`) và gợi ý; “Thử lại” là nút chính.

Trong khối căn giữa: logo + `texts.APP_NAME` (`title_label`, bậc chữ `theme.TextStyle.TITLE`, font điểm
nhấn nếu `ui.fonts.install()` đã nạp trước khi dựng cửa sổ), dòng trạng thái (SECTION), chi tiết, gợi
ý, form lần chạy đầu (chỉ WELCOME), nút căn phải. `title_label` nằm trong `start_view` nên ở RUNNING
không hiện.

**Bố cục hai cột** (RUNNING; cây widget ở spec B1 mục 2.3):
- `body` (`runningBody`): cột trái `sidebar` (`QFrame[surface="sidebar"]`, nền `sidebar`, viền phải
  1 px `border` nằm trong bề ngang của cột) và khung phải `stream_pane` (nền `surface`).
- Cột trái từ trên xuống: `sidebar_header` (logo 32 px, tên app, nút “Tìm máy mới” và “Cài đặt”),
  `sidebar_scroll` (danh sách cuộc trò chuyện `conversations`, `ui.conversations.ConversationList`, trong
  `sidebarContent`, nền trong suốt; nội dung cao hơn chỗ thì cuộn) và `machine_card`
  (`home.MachineCard`: máy này, địa chỉ, “Chép địa chỉ”, huy hiệu “Sẵn sàng nhận” / “Đang truyền n lượt”
  / “Không nhận file”). Model thiết bị `devices` (`radar.DeviceListModel`, cha là cửa sổ) dùng chung cho
  danh sách cuộc trò chuyện và trang DISCOVER; `ui.app` nạp nó. Danh sách cao đúng số hàng (không thanh
  cuộn riêng); hàng hiện hành đổi bằng bàn phím hay bằng code thì `sidebar_scroll` cuộn tới hàng đó.
- **Thu gọn** (`_apply_compact`, ở `resizeEvent` và `showEvent`; chỉ làm khi trạng thái đổi thật):
  cửa sổ hẹp hơn `COMPACT_BELOW` thì cột trái rộng `SIDEBAR_COMPACT_WIDTH` (`sidebar_compact`): danh
  sách chỉ còn avatar (`conversations.set_compact`), đầu cột xếp dọc và căn giữa, ẩn tên app,
  lề hẹp; `machine_card` ẩn, thay bằng `compact_machine` (`_CompactMachine`: avatar máy này, bấm để
  chép địa chỉ; tên, huy hiệu, địa chỉ ở mô tả trợ năng và tooltip). Tiêu điểm ở widget sắp ẩn
  (`name_label`, `address_label`, `copy_button`) → `compact_machine`; rời thu gọn mà tiêu điểm ở
  `compact_machine` → `name_label` (ẩn thì `copy_button`, rồi danh sách hay nút “＋”).
- Khung phải: `empty_state` (“Ghép đôi máy đầu tiên”) khi chưa có máy nào đã ghép đôi **và** luồng
  chat không có gì để hiện (không thông báo, không máy nào đang chọn; `set_transfer_summary`), không
  thì `transfers_area`, nơi `ui.transfers` đặt luồng chat của máy đang chọn (`ui.chat.ChatView`: thông
  báo, đầu luồng, bong bóng gửi/nhận và lịch sử, thanh “Gửi file” ở dưới; lề 0). Nút của
  `empty_state` chỉ có khi đã có trang DISCOVER.
- `save_bar` (`home.SaveBar`, “Lưu vào: …” + “Mở thư mục” + “Đổi…”) chạy hết chiều ngang dưới `body`;
  ẩn khi không biết thư mục nhận lẫn thư mục đã lưu hỏng. Bấm “Mở thư mục” phát
  `open_receive_dir_requested(Path)`, bấm “Đổi…” phát `change_receive_dir_requested` (`ui.app` mở
  hộp chọn qua `ui.receive_dir.ReceiveDirController`). Thư mục nhận, thư mục đã lưu hỏng và thư mục
  đang đổi sang được nhớ (`show_running`, `set_receive_dir`, `set_receive_dir_pending`) và chỉ áp vào
  `save_bar` và huy hiệu của `machine_card` ở RUNNING (ngoài RUNNING thanh ẩn, huy hiệu không báo
  “Không nhận file”). Node chạy mà không có thư mục nhận vì thư mục đã lưu hỏng → huy hiệu “Không
  nhận file” (`machine_card.set_receiving_unavailable`). Người dùng tạm dừng nhận ở menu khay
  (`set_receiving_paused`, `ui.app` gọi khi node xác nhận) → huy hiệu “Đã tạm dừng nhận”, cũng chỉ ở
  RUNNING (thứ tự ưu tiên ở docstring `ui.home`).
- Nút đầu cột chỉ hiện khi đã có trang tương ứng (`add_page`): không có nút bấm mà không làm gì.
- Không phần nào làm cửa sổ to hơn `MIN_SIZE`: cột trái cuộn bằng `sidebar_scroll`, khối căn giữa
  bằng `start_scroll`. Tiêu điểm đặt bằng code vào widget trong hai vùng cuộn đó thì vùng cuộn tự cuộn
  tới (danh sách cuộc trò chuyện: tới hàng hiện hành; `QApplication.focusChanged`; không khi tiêu điểm
  đến từ cú bấm chuột, để cú bấm vào hàng bị che một phần không trượt).

Dòng địa chỉ (`address_label`, trong `machine_card`) chỉ hiện ở RUNNING khi có ít nhất một địa chỉ:
địa chỉ đầu tiên, thêm `:cổng` khi cổng khác `DEFAULT_PORT`; các địa chỉ còn lại nằm ở tooltip (và
accessibleDescription). “Chép địa chỉ” chép đúng chuỗi đó. Rời RUNNING (`show_welcome`,
`show_starting`, `show_error`) thì quên địa chỉ đã nhớ. `ui.app` đọc địa chỉ qua `NodeHost.submit`
và gọi `set_addresses`.

**Trợ năng** (mvp N12): mọi chữ là chữ thuần (`Qt.PlainText`), có tên cho trình đọc màn hình; nhãn
chọn được bằng chuột nhưng không có con trỏ chữ khi Tab tới (không `TextSelectableByKeyboard`).
Thứ tự Tab ở RUNNING: “Tìm máy mới” → “Cài đặt” → từng hàng của danh sách cuộc trò chuyện → “Ghép
đôi máy mới” → tên máy này → địa chỉ → “Chép địa chỉ” → `compact_machine` → khung phải (luồng chat:
thông báo → luồng, một điểm dừng → “↓ Mới” → “Gửi file”, xem `ui.chat`) → “Mở thư
mục” → “Đổi…” (luôn cuối: widget tạo sau như luồng chat hay trang mới rơi vào cuối chuỗi, nên
`set_transfer_summary` và `add_page` dời hai nút về cuối bằng `_keep_footer_last`; “Mở thư mục” ẩn
thì Tab bỏ qua nó, “Đổi…” vẫn cuối). WELCOME: ô tên → “Đổi…” → công tắc (khi hiện) → “Bắt đầu”
(nhãn của form không nhận Tab). ERROR: dòng trạng thái → chi tiết → gợi ý → “Thử lại”. Tiêu điểm ban
đầu (`_place_focus`): WELCOME thì `first_run.focus_target()` (ô tên, con trỏ cuối chữ; có lỗi tên thì
chọn hết chữ; có lỗi thư mục thì “Đổi…”); ERROR thì “Thử lại”; RUNNING thì danh sách cuộc trò
chuyện khi có máy đã ghép đôi (`conversations.model.rowCount()`), không thì nút “Ghép đôi máy mới”;
STARTING thì dòng trạng thái. Trạng thái luôn nói bằng chữ, không chỉ bằng màu.

**Phím tắt**: danh sách phím và mô tả ở `ui.shortcuts` (nguồn duy nhất); `_install_shortcuts` dựng
các `QAction` `WindowShortcut` (`_discover_action`, `_settings_action`, `_open_dir_action`, chín
`_conversation_actions`, `_previous_action`, `_next_action`, `_back_action`, `_close_action`,
`_quit_action`, `_retry_action`) và `_update_shortcuts` bật/tắt chúng theo trạng thái và trang (gọi
mỗi khi trang, `ViewState` hay thư mục nhận đổi; action tắt thì phím đi tiếp tới widget, ví dụ
Alt+↓ của QComboBox). Ở RUNNING: Tìm máy mới / Cài đặt khi đã có trang đó (mọi trang), Mở thư mục
nhận khi có thư mục nhận; chỉ ở trang HOME: mở cuộc trò chuyện thứ n (`open_conversation_at`), chuyển
lên/xuống (`step_conversation`, không vòng, tự lặp khi giữ phím); cả hai đi qua `open_conversation`
nên tiêu điểm vào danh sách. Quay lại khi ở trang khác HOME; Đóng cửa sổ, Thoát, Thử lại luôn bật
(Thử lại chỉ chạy khi nút đang hiện). Tooltip của nút đầu cột, “＋”, “Mở thư mục”, “Quay lại”, “Thử
lại” ghi kèm phím. Phím Dán file và Chọn file gắn ở `ui.chat.ChatView`.

Cỡ cửa sổ lúc mở: `default_size(vùng dùng được của màn hình chính)` = `DEFAULT_SIZE` kẹp theo màn
hình; cỡ tối thiểu `MIN_SIZE`. Hình học, phóng to và màn hình được nhớ giữa các lần chạy
(`ui.placement`, `ui.app` áp lại trước khi hiện); `shown_once` cho biết cửa sổ đã từng hiện (chưa hiện
thì không có gì để lưu). `bring_to_front` khi đang thu nhỏ chỉ bỏ cờ thu nhỏ nên giữ phóng to.

Đóng cửa sổ (`closeEvent`): khay dùng được (`Tray.is_available()`) thì ẩn cửa sổ và phát
`hidden_to_tray` (app vẫn chạy và nhận file); không có khay thì phát `quit_requested`. Cửa sổ
không tự thoát app: `ui.app` quyết định. Ẩn xuống khay giữ nguyên trang đang mở.

**Khung trang** (spec A3): `centralWidget()` là `PageStack` (`self.pages`, objectName `pageStack`),
một `QStackedWidget`. Mọi thứ ở trên nằm trong trang HOME (`self.home_page`, objectName `homePage`);
các thuộc tính công khai (`conversations`, `transfers_area`, `body`, `status_label`…) giữ tên. Tên trang là
`Page` (HOME, DISCOVER, SETTINGS, WAIT_PAIRING); trang chỉ có khi được `add_page`.
- `PageStack.show_page(page)`: chưa có → KeyError; trùng trang hiện tại thì thôi; HOME xóa lịch sử;
  trang đã nằm trong lịch sử thì cắt lịch sử tới ngay trước nó (không vòng); còn lại đẩy (trang hiện
  tại, `window().focusWidget()`) vào lịch sử. Đổi xong đặt tiêu điểm vào trang (trang tự
  `setFocusProxy` tới control đầu tiên). `back()` lấy phần tử cuối, hiện trang đó và trả tiêu điểm về
  widget đã nhớ nếu nó còn sống, còn trong trang, hiện và bật; không thì vào trang. `reset()` về HOME,
  xóa lịch sử, không đặt tiêu điểm. `page_changed(str)` phát đúng một lần mỗi khi trang đổi thật
  (kể cả do `reset`).
- `MainWindow.open_page(page)`: trang khác HOME chỉ mở được ở RUNNING (các trang khác cần node đang
  chạy), không thì False và đứng yên. `go_back()` = `pages.back()`. `show_welcome`, `show_starting`,
  `show_error` gọi `pages.reset()` trước `retranslate`/`_place_focus`.
- Esc (`_back_action`, `WindowShortcut`, “Quay lại”) chỉ bật khi đang ở trang khác HOME. Hộp thoại
  là cửa sổ riêng nên không bị Esc của cửa sổ chính bắt. Ô nhập trên trang khác HOME phải nhận
  `ShortcutOverride` cho Esc nếu cần phím đó (như `_AddressField` của `ui.discover`).
- Trang DISCOVER (`self.discover`, `ui.discover.DiscoverPage`, “Tìm máy mới”) luôn có, đăng ký bằng
  `add_page` cuối `__init__` nên nút “Tìm máy mới” ở đầu cột, nút “＋ Ghép đôi máy mới” và nút của màn
  rỗng luôn mở được; dùng chung model `devices`; “Quay lại” của đầu trang = `go_back`.
- `open_conversation(id)`: về HOME, chọn máy đó trong danh sách, tiêu điểm vào danh sách; máy không có
  trong danh sách → False. `open_address_entry(notice)`: mở DISCOVER (chỉ ở RUNNING), rồi mới hiện
  `notice` ở thanh thông báo của trang (mức INFO; `DiscoverPage.showEvent` xóa thanh khi trang hiện) và
  đặt tiêu điểm vào ô “Nhập IP…”.
- Trang SETTINGS (`ui.settings.SettingsPage`) do `ui.app.GuiApp` đăng ký (`add_page`), không phải cửa
  sổ: `MainWindow` trần (test) không có nút ⚙. `set_device_name(name)` đổi tên ở thẻ máy này sau khi
  đổi tên trong Cài đặt.
- Không có hoạt ảnh chuyển trang: đổi tức thì.
"""

from __future__ import annotations

import contextlib
import functools
from collections.abc import Sequence
from enum import StrEnum
from itertools import pairwise
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QModelIndex,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAccessible,
    QAccessibleEvent,
    QAction,
    QCloseEvent,
    QGuiApplication,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QScrollArea,
    QStackedWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from teleport import paths
from teleport.net.connection import DEFAULT_PORT
from teleport.ui import first_run, shortcuts, texts, theme
from teleport.ui.backdrop import MicaBackdrop
from teleport.ui.conversations import ConversationList
from teleport.ui.discover import DiscoverPage
from teleport.ui.first_run import FirstRunChoice, TextSource
from teleport.ui.home import START_PANEL_MAX_WIDTH as START_PANEL_MAX_WIDTH  # hằng của bảng spec B1 mục 2.3
from teleport.ui.home import MachineCard, SaveBar, StartPanel
from teleport.ui.radar import DeviceListModel
from teleport.ui.shortcuts import Shortcut
from teleport.ui.tray import Tray, make_icon
from teleport.ui.widgets import (
    AvatarKind,
    EmptyState,
    IconButton,
    Presence,
    paint_avatar,
    safe_tooltip,
)

DEFAULT_SIZE = QSize(980, 660)  # cỡ cửa sổ lúc mở khi màn hình đủ rộng
MIN_SIZE = QSize(720, 460)
SIDEBAR_WIDTH = 288  # px, cột trái (kể cả viền phải 1 px)
SIDEBAR_COMPACT_WIDTH = 80  # px, cột trái thu gọn (chỉ còn avatar) khi cửa sổ hẹp
COMPACT_BELOW = 820  # px: cửa sổ hẹp hơn thì cột trái thu gọn
SETTINGS_SHORTCUT = shortcuts.portable_text(Shortcut.SETTINGS)  # mở trang Cài đặt
_BRAND_LOGO = 32  # px
_LAYOUT_PASSES = 5  # tối đa số lượt chạy layout trước khi cuộn tới widget có tiêu điểm
_COMPACT_MACHINE = 48  # px, nút “Máy này” khi cột trái thu gọn
_COMPACT_AVATAR = 40  # px
_COPIED_TOOLTIP_MS = 2000
_HEADER_MARGINS = (16, 16, 12, 8)  # px, đầu cột trái dạng đầy đủ
_HEADER_COMPACT_MARGINS = (0, 12, 0, 8)
_CONTENT_MARGINS = (theme.SPACING[2], 0, theme.SPACING[2], theme.SPACING[2])  # px, lề `sidebarContent`
_CONTENT_COMPACT_MARGINS = (4, 0, 4, 8)


def default_size(available: QSize) -> QSize:
    """Cỡ cửa sổ lúc mở: `DEFAULT_SIZE` kẹp theo vùng dùng được của màn hình (`available`)."""
    return QSize(min(DEFAULT_SIZE.width(), available.width()), min(DEFAULT_SIZE.height(), available.height()))


class Page(StrEnum):
    """Tên trang của cửa sổ chính; trang chỉ có khi được `add_page` (B5, D2, D3 thêm trang của mình)."""

    HOME = "home"
    DISCOVER = "discover"
    SETTINGS = "settings"
    WAIT_PAIRING = "wait_pairing"


class PageStack(QStackedWidget):
    """Chồng trang của cửa sổ chính, có lịch sử để quay lại (xem docstring module, “Khung trang”)."""

    page_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageStack")
        self._pages: dict[Page, QWidget] = {}
        # (trang trước, widget có tiêu điểm lúc rời trang đó)
        self._history: list[tuple[Page, QWidget | None]] = []

    def add_page(self, page: Page, widget: QWidget) -> None:
        """Thêm trang; trùng → ValueError. Đặt objectName `<page>Page` nếu widget chưa có tên."""
        page = Page(page)
        if page in self._pages:
            raise ValueError(f"trang đã có: {page}")
        if not widget.objectName():
            widget.setObjectName(f"{page}Page")
        self._pages[page] = widget
        self.addWidget(widget)

    def has_page(self, page: Page) -> bool:
        return page in self._pages

    @property
    def current_page(self) -> Page:
        current = self.currentWidget()
        for page, widget in self._pages.items():
            if widget is current:
                return page
        return Page.HOME

    def show_page(self, page: Page) -> None:
        """Hiện trang `page` (chưa có → KeyError) và đặt tiêu điểm vào nó; ghi lịch sử để quay lại."""
        page = Page(page)
        widget = self._pages[page]
        current = self.current_page
        if page is current:
            return
        if page is Page.HOME:
            self._history.clear()
        else:
            index = next((i for i, (seen, _) in enumerate(self._history) if seen is page), None)
            if index is not None:
                del self._history[index:]  # không tạo vòng
            else:
                self._history.append((current, self.window().focusWidget()))
        self._switch(page, widget)
        widget.setFocus(Qt.FocusReason.OtherFocusReason)

    def back(self) -> bool:
        """Về trang trước trong lịch sử và trả tiêu điểm đã nhớ; lịch sử rỗng → False."""
        if not self._history:
            return False
        page, focus = self._history.pop()
        widget = self._pages[page]
        self._switch(page, widget)
        window = self.window()
        if (
            focus is not None
            and isValid(focus)
            and (focus is widget or widget.isAncestorOf(focus))
            and focus.isVisibleTo(window)
            and focus.isEnabled()
        ):
            focus.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            widget.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def reset(self) -> None:
        """Về HOME, xóa lịch sử; không đặt tiêu điểm (bên gọi lo)."""
        self._history.clear()
        if Page.HOME in self._pages and self.current_page is not Page.HOME:
            self._switch(Page.HOME, self._pages[Page.HOME])

    def _switch(self, page: Page, widget: QWidget) -> None:
        self.setCurrentWidget(widget)
        self.page_changed.emit(str(page))


class ViewState(StrEnum):
    WELCOME = "welcome"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class _CompactMachine(QAbstractButton):
    """“Máy này” khi cột trái thu gọn: avatar 48 px thay cho `machine_card` (spec B2 mục 2.6).

    Bấm (chuột, Space) chép địa chỉ như “Chép địa chỉ” của `machine_card` (clipboard, tooltip “Đã chép
    địa chỉ …”, sự kiện trợ năng Alert, `machine_card.address_copied`); chưa có địa chỉ thì không làm
    gì. Tên, chữ huy hiệu và địa chỉ nằm ở mô tả trợ năng và tooltip (`update_info`). Nền `selected` khi
    rê chuột, viền tiêu điểm 2 px `focus_ring_color`; chấm của avatar: ONLINE khi không có lượt nào,
    BUSY khi đang truyền (chữ ở huy hiệu trong mô tả).
    """

    def __init__(self, card: MachineCard, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("compactMachine")
        self._card = card
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(_COMPACT_MACHINE, _COMPACT_MACHINE)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.clicked.connect(self._copy)
        self.update_info()

    def update_info(self) -> None:
        """Dựng lại tên, mô tả trợ năng và tooltip từ `machine_card` (tên, huy hiệu, địa chỉ)."""
        t = QCoreApplication.translate
        self.setAccessibleName(t("Home", "Máy này"))
        card = self._card
        parts = [card.name_label.text(), card.badge.text, card.address_label.text()]
        sentences = [part if part.endswith((".", "…")) else part + "." for part in parts if part]
        if card.copy_value is not None:
            sentences.append(t("MainWindow", "Bấm để chép địa chỉ."))
        text = " ".join(sentences)
        self.setAccessibleDescription(text)
        self.setToolTip(safe_tooltip(text) if text else "")
        self.update()

    def _copy(self) -> None:
        value = self._card.copy_value
        if value is None:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(value)
        message = texts.fill(QCoreApplication.translate("Home", "Đã chép địa chỉ {address}"), address=value)
        QToolTip.showText(
            self.mapToGlobal(QPoint(0, self.height())),
            safe_tooltip(message),
            self,
            QRect(),
            _COPIED_TOOLTIP_MS,
        )
        # Cố gắng tốt nhất: có HĐH không chuyển Alert tới trình đọc màn hình.
        with contextlib.suppress(Exception):
            QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Event.Alert))
        self._card.address_copied.emit(value)

    def sizeHint(self) -> QSize:
        return QSize(_COMPACT_MACHINE, _COMPACT_MACHINE)

    def paintEvent(self, event: QPaintEvent) -> None:
        t = theme.tokens_for(self)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            cell = QRectF(self.rect())
            hovered = self.underMouse() or self.isDown()
            if hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(t.selected)
                painter.drawRoundedRect(cell, theme.RADIUS_CARD, theme.RADIUS_CARD)
            inset = (_COMPACT_MACHINE - _COMPACT_AVATAR) / 2
            paint_avatar(
                painter,
                cell.adjusted(inset, inset, -inset, -inset),
                kind=AvatarKind.DESKTOP,
                presence=Presence.ONLINE if self._card.active == 0 else Presence.BUSY,
                emphasis=True,
                ring=t.selected if hovered else t.sidebar,
                tokens=t,
                dpr=self.devicePixelRatioF(),
            )
            if self.hasFocus():
                dark = theme.is_dark_palette(QApplication.palette())
                painter.setPen(QPen(theme.focus_ring_color(dark), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(cell.adjusted(1, 1, -1, -1), theme.RADIUS_CARD, theme.RADIUS_CARD)
        finally:
            painter.end()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.update()


class MainWindow(QMainWindow):
    """Cửa sổ chính; trạng thái đổi bằng các hàm `show_*`."""

    retry_requested = Signal()
    start_requested = Signal(object)  # FirstRunChoice; chỉ `ui.app.GuiApp` nối
    change_first_run_dir_requested = Signal()  # nối thẳng từ `first_run.change_dir_requested`
    quit_requested = Signal()
    hidden_to_tray = Signal()
    page_changed = Signal(str)  # giá trị `Page`; nối thẳng từ `PageStack.page_changed`
    open_receive_dir_requested = Signal(object)  # Path; nối thẳng từ `save_bar.open_requested`
    change_receive_dir_requested = Signal()  # nối thẳng từ `save_bar.change_requested`

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("mainWindow")
        self.setMinimumSize(MIN_SIZE)
        screen = QGuiApplication.primaryScreen()
        self.resize(DEFAULT_SIZE if screen is None else default_size(screen.availableGeometry().size()))
        self._state = ViewState.STARTING
        self._name: str | None = None
        self._receive_dir: Path | None = None
        self._receive_dir_unavailable: Path | None = None
        self._receive_dir_pending: Path | None = None
        self._receiving_paused = False  # người dùng tạm dừng nhận (menu khay, spec D4)
        self._shortcuts_ready = False  # `_install_shortcuts` xong; trước đó `_update_shortcuts` bỏ qua
        self._error_code = ""
        self._error_detail = ""
        self._addresses: tuple[str, ...] = ()
        self._port: int | None = None
        self._has_content = False  # luồng chat có bong bóng hay thanh thông báo (`set_transfer_summary`)
        self._active = 0
        self._progress: int | None = None  # % tổng trên tiêu đề cửa sổ (`set_progress`)
        self._has_paired = False  # danh sách cuộc trò chuyện có máy (đã ghép đôi)
        self._scroll_target: QWidget | None = None  # widget chờ được cuộn tới (`_on_focus_changed`)
        self._compact_applied: bool | None = None  # dạng cột trái đã áp (`_apply_compact`)
        self._shown_once = False  # cửa sổ đã từng hiện (`ui.placement.capture`)
        # Các thiết bị (ảnh chụp `devices()` + `NodeEvent`), dùng chung cho danh sách cuộc trò chuyện
        # và trang “Tìm máy mới”.
        self.devices = DeviceListModel(self)

        # Trang HOME: khối căn giữa (WELCOME / STARTING / ERROR) hay khung hai cột (RUNNING).
        self.pages = PageStack(self)
        self.home_page = QWidget(self.pages)
        self.home_page.setObjectName("homePage")
        home_layout = QVBoxLayout(self.home_page)
        home_layout.setContentsMargins(0, 0, 0, 0)
        home_layout.setSpacing(0)
        self.home_stack = QStackedWidget(self.home_page)
        self.home_stack.setObjectName("homeStack")
        home_layout.addWidget(self.home_stack)

        self.start_view = StartPanel(self.home_stack)
        self.title_label = self.start_view.title_label
        self.status_icon = self.start_view.status_icon
        self.status_label = self.start_view.status_label
        self.detail_label = self.start_view.detail_label
        self.hint_label = self.start_view.hint_label
        self.starting_bar = self.start_view.starting_bar
        self.retry_button = self.start_view.retry_button
        self.start_button = self.start_view.start_button
        self.first_run = self.start_view.first_run
        self.retry_button.clicked.connect(self.retry_requested)
        self.start_button.clicked.connect(self._submit_first_run)
        self.first_run.submitted.connect(self._submit_first_run)
        self.first_run.change_dir_requested.connect(self.change_first_run_dir_requested)

        self.shell = QWidget(self.home_stack)
        self.shell.setObjectName("runningShell")
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self.body = QWidget(self.shell)
        self.body.setObjectName("runningBody")
        body_layout = QHBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # Cột trái: đầu cột, danh sách cuộc trò chuyện cuộn được, máy này.
        self.sidebar = QFrame(self.body)
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setProperty(theme.SURFACE_PROPERTY, "sidebar")
        self.sidebar.setFixedWidth(SIDEBAR_WIDTH)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        self.sidebar_header = QWidget(self.sidebar)
        self.sidebar_header.setObjectName("sidebarHeader")
        self.brand_logo = QLabel(self.sidebar_header)
        self.brand_logo.setObjectName("brandLogo")
        self.brand_logo.setTextFormat(Qt.TextFormat.PlainText)
        self.brand_logo.setFixedSize(_BRAND_LOGO, _BRAND_LOGO)
        self.brand_logo.setPixmap(make_icon().pixmap(_BRAND_LOGO))
        self.brand_logo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.brand_label = QLabel(self.sidebar_header)
        self.brand_label.setObjectName("brandLabel")
        self.brand_label.setTextFormat(Qt.TextFormat.PlainText)
        self.brand_label.setFont(theme.font_for(theme.TextStyle.TITLE, self.brand_label.font()))
        self.brand_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.discover_button = IconButton(
            "search",
            QCoreApplication.translate("MainWindow", "Tìm máy mới"),
            self.sidebar_header,
            shortcut=shortcuts.sequence(Shortcut.DISCOVER),
        )
        self.discover_button.setObjectName("discoverButton")
        self.discover_button.clicked.connect(self._open_discover)
        self.settings_button = IconButton(
            "settings",
            QCoreApplication.translate("MainWindow", "Cài đặt"),
            self.sidebar_header,
            shortcut=shortcuts.sequence(Shortcut.SETTINGS),
        )
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.clicked.connect(self._open_settings)
        # Thu gọn thì cả hai hàng xếp dọc (`setDirection`) và căn giữa (`_apply_compact`).
        self.header_layout = QHBoxLayout(self.sidebar_header)
        self.header_layout.setContentsMargins(*_HEADER_MARGINS)
        self.header_layout.setSpacing(theme.SPACING[1])
        self.header_layout.addWidget(self.brand_logo, 0, Qt.AlignmentFlag.AlignVCenter)
        self.header_layout.addWidget(self.brand_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.header_layout.addStretch(1)
        self.header_buttons = QHBoxLayout()
        self.header_buttons.setSpacing(theme.SPACING[0])
        self.header_buttons.addWidget(self.discover_button)
        self.header_buttons.addWidget(self.settings_button)
        self.header_layout.addLayout(self.header_buttons)

        self.sidebar_scroll = QScrollArea(self.sidebar)
        self.sidebar_scroll.setObjectName("sidebarScroll")
        self.sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # mặc định StrongFocus: Tab ghé vô ích
        sidebar_content = QWidget()
        sidebar_content.setObjectName("sidebarContent")
        self._content_layout = QVBoxLayout(sidebar_content)
        self._content_layout.setContentsMargins(*_CONTENT_MARGINS)
        self._content_layout.setSpacing(0)
        self.conversations = ConversationList(self.devices, sidebar_content)
        self._content_layout.addWidget(self.conversations)
        self.sidebar_scroll.setWidget(sidebar_content)
        # `setWidget` bật autofill: tắt lại để thấy nền `sidebar` của cột.
        viewport = self.sidebar_scroll.viewport()
        if viewport is not None:
            viewport.setAutoFillBackground(False)
        sidebar_content.setAutoFillBackground(False)
        self.conversations.add_device_requested.connect(self._open_discover)

        self.machine_card = MachineCard(self.sidebar)
        self.name_label = self.machine_card.name_label
        self.address_label = self.machine_card.address_label
        self.copy_button = self.machine_card.copy_button
        self.badge = self.machine_card.badge
        # Thu gọn: nút “Máy này” chỉ có avatar thay chỗ `machine_card`, ngay dưới nó, căn giữa.
        self.compact_footer = QWidget(self.sidebar)
        self.compact_footer.setObjectName("compactFooter")
        footer_layout = QVBoxLayout(self.compact_footer)
        footer_layout.setContentsMargins(0, theme.SPACING[1], 0, theme.SPACING[1])
        self.compact_machine = _CompactMachine(self.machine_card, self.compact_footer)
        footer_layout.addWidget(self.compact_machine, 0, Qt.AlignmentFlag.AlignHCenter)
        self.compact_footer.setVisible(False)
        self.compact_machine.setVisible(False)

        sidebar_layout.addWidget(self.sidebar_header)
        sidebar_layout.addWidget(self.sidebar_scroll, 1)
        sidebar_layout.addWidget(self.machine_card)
        sidebar_layout.addWidget(self.compact_footer)

        # Khung phải: màn rỗng hay luồng chat (`ui.chat`).
        self.stream_pane = QStackedWidget(self.body)
        self.stream_pane.setObjectName("streamPane")
        self.empty_state = EmptyState(self.stream_pane)
        self.empty_state.setObjectName("streamEmpty")
        self.empty_state.action_triggered.connect(self._open_discover)
        self.transfers_area = QWidget(self.stream_pane)
        self.transfers_area.setObjectName("transfersArea")
        area_layout = QVBoxLayout(self.transfers_area)
        area_layout.setContentsMargins(*(theme.SPACING[3],) * 4)
        self.stream_pane.addWidget(self.empty_state)
        self.stream_pane.addWidget(self.transfers_area)

        body_layout.addWidget(self.sidebar)
        body_layout.addWidget(self.stream_pane, 1)

        self.save_bar = SaveBar(self.shell)
        self.save_bar.open_requested.connect(self.open_receive_dir_requested)
        self.save_bar.change_requested.connect(self.change_receive_dir_requested)
        shell_layout.addWidget(self.body, 1)
        shell_layout.addWidget(self.save_bar)

        self.home_stack.addWidget(self.start_view)
        self.home_stack.addWidget(self.shell)

        self.pages.add_page(Page.HOME, self.home_page)
        self.discover = DiscoverPage(self.devices, self.pages)
        self.discover.header.back_requested.connect(self.go_back)
        self.pages.page_changed.connect(self.page_changed)
        self.pages.page_changed.connect(self._on_page_changed)
        self.setCentralWidget(self.pages)

        # Thứ tự Tab: khối căn giữa (`StartPanel` tự nối) rồi khung hai cột; widget ẩn tự bị bỏ qua.
        empty = self.empty_state
        chain: list[QWidget] = [
            self.status_label,
            self.detail_label,
            self.hint_label,
            self.first_run.name_edit,
            self.first_run.dir_button,
            self.first_run.autostart_switch,
            self.retry_button,
            self.start_button,
            self.discover_button,
            self.settings_button,
            self.conversations.first_focus_widget(),
        ]
        for first, second in pairwise(chain):
            QWidget.setTabOrder(first, second)
        rest: list[QWidget] = [
            self.conversations.last_focus_widget(),
            self.name_label,
            self.address_label,
            self.copy_button,
            self.compact_machine,
            empty.title_label,
            empty.text_label,
            empty.action_button,
            self.save_bar.open_button,  # nội dung của `transfers_area` tạo sau: `_keep_footer_last`
            self.save_bar.change_button,
        ]
        for first, second in pairwise(rest):
            QWidget.setTabOrder(first, second)

        model = self.conversations.model
        for signal in (model.modelReset, model.rowsInserted, model.rowsRemoved, model.layoutChanged):
            signal.connect(self._update_paired)
        selection = self.conversations.list_view.selectionModel()
        if selection is not None:
            selection.currentChanged.connect(self._on_conversation_current)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.focusChanged.connect(self._on_focus_changed)

        self._install_shortcuts()

        self.add_page(Page.DISCOVER, self.discover)  # cũng dời “Mở thư mục” về cuối chuỗi Tab
        self._update_page_buttons()
        self.retranslate()
        self.backdrop = MicaBackdrop(self, self.sidebar)  # nền Mica cột trái (Windows 11, spec G7)

    # ---- Trạng thái --------------------------------------------------------------------------

    @property
    def view_state(self) -> ViewState:
        return self._state

    @property
    def receive_dir(self) -> Path | None:
        """Thư mục nhận đã nhớ (`show_running` hay `set_receive_dir` gần nhất); None khi không nhận file."""
        return self._receive_dir

    @property
    def receive_dir_unavailable(self) -> Path | None:
        """Thư mục nhận đã lưu không mở được (đã nhớ), hay None."""
        return self._receive_dir_unavailable

    @property
    def receive_dir_pending(self) -> Path | None:
        """Thư mục đang đổi sang (đã nhớ), hay None."""
        return self._receive_dir_pending

    @property
    def sidebar_compact(self) -> bool:
        """Cột trái đang thu gọn (cửa sổ hẹp hơn `COMPACT_BELOW`)."""
        return self.width() < COMPACT_BELOW

    def show_welcome(
        self,
        planned_name: str,
        receive_dir: Path | None = None,
        *,
        autostart: bool | None = None,
        autostart_hint: TextSource = "",
        choice: FirstRunChoice | None = None,
        dir_error: TextSource = "",
    ) -> None:
        """Màn lần chạy đầu: `planned_name` là tên gợi ý (rỗng → ô trống có placeholder),
        `receive_dir` thư mục gợi ý (None → `paths.default_receive_dir()`, không tạo thư mục),
        `autostart` trạng thái ban đầu của công tắc (None → ẩn hàng), `autostart_hint` câu trạng thái
        registry; `choice` hiện lại lựa chọn trước, `dir_error` lỗi dưới hàng thư mục."""
        self._state = ViewState.WELCOME
        form = self.first_run
        form.set_defaults(
            planned_name,
            paths.default_receive_dir() if receive_dir is None else receive_dir,
            autostart,
            autostart_hint,
        )
        if choice is not None:
            form.restore(choice)
        if dir_error:
            form.set_dir_error(dir_error)
        self._forget_addresses()
        self.pages.reset()
        self.retranslate()
        self._place_focus()

    def show_starting(self) -> None:
        self._state = ViewState.STARTING
        self._forget_addresses()
        self.pages.reset()
        self.retranslate()
        self._place_focus()

    def show_running(
        self, name: str | None, receive_dir: Path | None, unavailable: Path | None = None
    ) -> None:
        """Node đã chạy: `receive_dir` là thư mục nhận (None: không nhận file), `unavailable` là thư
        mục đã lưu không mở được."""
        self._state = ViewState.RUNNING
        self._name, self._receive_dir = name, receive_dir
        self._receive_dir_unavailable = unavailable
        self.retranslate()
        self._place_focus()

    def set_receive_dir(self, receive_dir: Path | None, unavailable: Path | None = None) -> None:
        """Nhớ thư mục nhận và thư mục đã lưu hỏng; chỉ hiện ở RUNNING (chân “Lưu vào”, huy hiệu)."""
        self._receive_dir = receive_dir
        self._receive_dir_unavailable = unavailable
        self._apply_receive_dir()

    def set_receive_dir_pending(self, path: Path | None) -> None:
        """Nhớ thư mục đang đổi sang (“Đang đổi sang …”); None khi không đổi."""
        self._receive_dir_pending = path
        self._apply_receive_dir()

    def show_error(self, code: str, detail: str = "") -> None:
        """Lỗi khởi động node: `code` là `bridge.StartError`, `detail` đã làm sạch."""
        self._state = ViewState.ERROR
        self._error_code, self._error_detail = code, detail
        self._forget_addresses()
        self.pages.reset()
        self.retranslate()
        self._place_focus()

    def set_device_name(self, name: str) -> None:
        """Tên mới của máy này (đổi trong Cài đặt; chưa qua `display_name`): cập nhật thẻ máy này."""
        self._name = name
        if self._state is ViewState.RUNNING:
            self.machine_card.set_name(name)
            self.compact_machine.update_info()

    def set_receiving_paused(self, paused: bool) -> None:
        """Người dùng tạm dừng nhận file (menu khay, đã được node xác nhận): huy hiệu “Đã tạm dừng
        nhận” ở thẻ máy này và ở avatar khi cột thu gọn; chỉ hiện ở RUNNING."""
        self._receiving_paused = bool(paused)
        self._apply_receive_dir()
        self.compact_machine.update_info()

    def set_machine_hidden(self, hidden: bool) -> None:
        """Máy này đang ẩn (Cài đặt): huy hiệu “Đang ẩn” ở thẻ máy này và ở avatar khi cột thu gọn."""
        self.machine_card.set_hidden(hidden)
        self.compact_machine.update_info()

    def set_transfer_summary(self, has_content: bool, active: int) -> None:
        """Danh sách lượt có gì không (thẻ hay dải thông báo) và số lượt chưa kết thúc (≥ 0).

        Cập nhật huy hiệu của máy này, chọn `empty_state` / `transfers_area`, giữ nút “Mở thư mục”
        và “Đổi…” cuối chuỗi Tab. `active` < 0 → ValueError.
        """
        if active < 0:
            raise ValueError(f"số lượt phải ≥ 0: {active}")
        self._has_content = bool(has_content)
        self._active = active
        self.machine_card.set_activity(active)
        self.compact_machine.update_info()
        self._update_stream()
        self._keep_footer_last()

    def set_progress(self, percent: int | None) -> None:
        """% tổng trên tiêu đề cửa sổ (`texts.window_title`; None: chỉ tên app). `ui.transfers` gọi."""
        self._progress = percent
        self.setWindowTitle(texts.window_title(percent))

    # ---- Trang -------------------------------------------------------------------------------

    @property
    def current_page(self) -> Page:
        return self.pages.current_page

    def add_page(self, page: Page, widget: QWidget) -> None:
        """Thêm trang `page` (xem `PageStack.add_page`); hiện nút đầu cột và nút của màn rỗng tương ứng."""
        self.pages.add_page(page, widget)
        self._update_page_buttons()
        self._update_shortcuts()
        self._update_empty_content()
        self._keep_footer_last()

    def open_page(self, page: Page) -> bool:
        """Mở trang `page`; trang khác HOME chỉ mở được ở RUNNING (không thì False, đứng yên)."""
        page = Page(page)
        if page is not Page.HOME and self._state is not ViewState.RUNNING:
            return False
        self.pages.show_page(page)
        self._ensure_home_focus()
        return True

    def go_back(self) -> bool:
        """Về trang trước (Esc); không có trang trước thì False."""
        moved = self.pages.back()
        if moved:
            self._ensure_home_focus()
        return moved

    def open_conversation(self, device_id: str) -> bool:
        """Về HOME, chọn cuộc trò chuyện của máy `device_id` và đặt tiêu điểm vào danh sách.

        Máy không có trong danh sách (chưa ghép đôi, không biết) → False, đứng yên."""
        if self.conversations.model.row_of(device_id) < 0:
            return False
        if not self.open_page(Page.HOME):
            return False
        self.conversations.select_device(device_id)
        self.conversations.list_view.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def open_address_entry(self, notice: texts.Text | None = None) -> bool:
        """Mở trang “Tìm máy mới”, hiện `notice` (mức INFO) ở thanh thông báo của trang và đặt tiêu điểm
        vào ô “Nhập IP…” (chọn hết chữ). Không ở RUNNING → False.

        Mở trang **trước** rồi mới hiện câu: `DiscoverPage.showEvent` xóa thanh thông báo (câu cũ)."""
        if not self.open_page(Page.DISCOVER):
            return False
        if notice:
            self.discover.show_info(notice)
        self.discover.address_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.discover.address_edit.selectAll()
        return True

    def _ensure_home_focus(self) -> None:
        """Về HOME mà tiêu điểm rơi vào chính `home_page` (không nhận tiêu điểm, không proxy) hay không
        vào đâu được thì đặt lại theo `_place_focus`."""
        if self.pages.current_page is not Page.HOME:
            return
        focus = self.focusWidget()
        if (
            focus is None
            or focus is self.home_page
            or not self.home_page.isAncestorOf(focus)
            or focus.focusPolicy() == Qt.FocusPolicy.NoFocus
            or not focus.isVisibleTo(self)
        ):
            self._place_focus()

    def _open_discover(self) -> None:
        self.open_page(Page.DISCOVER)

    def _open_settings(self) -> None:
        if self.pages.has_page(Page.SETTINGS):
            self.open_page(Page.SETTINGS)

    def _on_page_changed(self, _page: str) -> None:
        self._update_shortcuts()

    def _update_page_buttons(self) -> None:
        self.discover_button.setVisible(self.pages.has_page(Page.DISCOVER))
        self.settings_button.setVisible(self.pages.has_page(Page.SETTINGS))

    def set_addresses(self, addresses: Sequence[str], port: int | None) -> None:
        """Địa chỉ IPv4 của máy này và cổng đang lắng nghe (`Node.local_addresses`, `Node.port`).

        Nhớ lại để `retranslate` dựng lại chữ; chỉ hiện ở RUNNING và khi `addresses` khác rỗng.
        """
        self._addresses = tuple(addresses)
        self._port = port
        self._update_address()

    def _forget_addresses(self) -> None:
        self._addresses, self._port = (), None

    def _place_focus(self) -> None:
        """Đặt tiêu điểm bàn phím: WELCOME thì `first_run.focus_target()`; ERROR thì “Thử lại”; RUNNING
        thì danh sách cuộc trò chuyện (có máy đã ghép đôi) hay nút “Ghép đôi máy mới”; còn lại
        (STARTING) dòng trạng thái.

        Đang ở trang khác HOME thì thôi (`show_running` không đưa về HOME; trang đó tự giữ tiêu điểm)."""
        if self.pages.current_page is not Page.HOME:
            return
        if self._state is ViewState.WELCOME:
            self.first_run.focus_target().setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if self.retry_button.isVisibleTo(self):
            self.retry_button.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if self._state is ViewState.RUNNING:
            conversations = self.conversations
            target: QWidget = (
                conversations.list_view if conversations.model.rowCount() > 0 else conversations.add_button
            )
            target.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        self.status_label.setFocus(Qt.FocusReason.OtherFocusReason)

    @property
    def shown_once(self) -> bool:
        """Cửa sổ đã hiện ít nhất một lần (từ đó hình học mới đáng lưu)."""
        return self._shown_once

    def bring_to_front(self) -> None:
        """Hiện lại cửa sổ (kể cả khi đang thu nhỏ hay ẩn) và đưa lên trước; giữ phóng to."""
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    # ---- Chữ ---------------------------------------------------------------------------------

    def retranslate(self) -> None:
        """Đặt lại mọi chữ theo ngôn ngữ hiện tại và trạng thái hiện tại."""
        self.setWindowTitle(texts.window_title(self._progress))
        self.title_label.setText(texts.APP_NAME)
        self.title_label.setAccessibleName(QCoreApplication.translate("MainWindow", "Tên ứng dụng"))
        self.brand_label.setText(texts.APP_NAME)
        self.brand_label.setAccessibleName(texts.APP_NAME)
        self.retry_button.setText(texts.retry())
        self.retry_button.setAccessibleName(texts.retry())
        self.retry_button.setToolTip(
            texts.fill(
                QCoreApplication.translate("MainWindow", "Khởi động lại Teleport ({key})"),
                key=shortcuts.key_text(Shortcut.RETRY),
            )
        )
        start = QCoreApplication.translate("MainWindow", "Bắt đầu")
        self.start_button.setText(start)
        self.start_button.setAccessibleName(start)
        self.start_button.setAccessibleDescription(first_run.consent_text())
        self.discover_button.set_label(QCoreApplication.translate("MainWindow", "Tìm máy mới"))
        self.settings_button.set_label(QCoreApplication.translate("MainWindow", "Cài đặt"))
        self.sidebar.setAccessibleName(QCoreApplication.translate("MainWindow", "Thiết bị"))
        transfers = QCoreApplication.translate("MainWindow", "Lượt truyền")
        self.stream_pane.setAccessibleName(transfers)
        self.transfers_area.setAccessibleName(transfers)
        shortcuts.retranslate_actions(self)
        self.start_view.retranslate()
        self.machine_card.retranslate()
        self.save_bar.retranslate()

        status, detail, hints = self._content()
        self.status_label.setText(status)
        self.status_label.setVisible(bool(status))  # WELCOME: form lần chạy đầu thay dòng trạng thái
        self.status_label.setAccessibleName(QCoreApplication.translate("MainWindow", "Trạng thái"))
        self.status_label.setAccessibleDescription(status)
        self._set_optional(self.detail_label, detail, QCoreApplication.translate("MainWindow", "Chi tiết"))
        self._set_optional(
            self.hint_label, "\n".join(hints), QCoreApplication.translate("MainWindow", "Gợi ý")
        )
        self._update_address()
        running = self._state is ViewState.RUNNING
        self.home_stack.setCurrentWidget(self.shell if running else self.start_view)
        self.start_view.set_error_icon(self._state is ViewState.ERROR)
        self.starting_bar.setVisible(self._state is ViewState.STARTING)
        self.retry_button.setVisible(self._state is ViewState.ERROR)
        self.start_button.setVisible(self._state is ViewState.WELCOME)
        self.first_run.setVisible(self._state is ViewState.WELCOME)
        self.machine_card.set_name(self._name if running else None)
        self.compact_machine.update_info()
        self._apply_receive_dir()
        self._update_empty_content()
        self._update_stream()
        self._update_shortcuts()

    def _apply_receive_dir(self) -> None:
        """Áp thư mục nhận đã nhớ vào `save_bar` và huy hiệu; ngoài RUNNING thì xóa cả hai."""
        running = self._state is ViewState.RUNNING
        receive_dir = self._receive_dir if running else None
        unavailable = self._receive_dir_unavailable if running else None
        self.save_bar.set_state(receive_dir, unavailable, self._receive_dir_pending if running else None)
        self.machine_card.set_receiving_unavailable(
            running and receive_dir is None and unavailable is not None
        )
        self.machine_card.set_receiving_paused(running and self._receiving_paused)
        self._update_shortcuts()

    def _content(self) -> tuple[str, str, list[str]]:
        """(dòng trạng thái, dòng chi tiết, các dòng gợi ý) của khối căn giữa; WELCOME (form lần chạy
        đầu thay chỗ) và RUNNING thì rỗng."""
        if self._state is ViewState.STARTING:
            return QCoreApplication.translate("MainWindow", "Đang khởi động…"), "", []
        if self._state is ViewState.WELCOME:
            return "", "", []
        if self._state is ViewState.RUNNING:
            return "", "", []  # tên, địa chỉ, huy hiệu ở `machine_card`; thư mục nhận ở `save_bar`
        head, hints = texts.start_error(self._error_code, self._error_detail)
        return QCoreApplication.translate("MainWindow", "Không khởi động được"), head, hints

    def _update_address(self) -> None:
        """Dựng dòng “Địa chỉ: …”, tooltip các địa chỉ khác và chuỗi để chép từ giá trị đã nhớ."""
        suffix = f":{self._port}" if self._port is not None and self._port != DEFAULT_PORT else ""
        shown = [f"{address}{suffix}" for address in self._addresses]
        text = ""
        if self._state is ViewState.RUNNING and shown:
            text = texts.fill(
                QCoreApplication.translate("MainWindow", "Địa chỉ: {address}"), address=shown[0]
            )
        others = ""
        if text and len(shown) > 1:
            others = texts.fill(
                QCoreApplication.translate("MainWindow", "Các địa chỉ khác của máy này: {list}"),
                list=", ".join(shown[1:]),
            )
        self.address_label.setText(text)
        self.address_label.setAccessibleName(QCoreApplication.translate("MainWindow", "Địa chỉ của máy này"))
        self.address_label.setAccessibleDescription(others)
        self.address_label.setToolTip(others)
        self.address_label.setVisible(bool(text))
        self.machine_card.set_copy_value(shown[0] if text else None)
        self.compact_machine.update_info()

    def _update_empty_content(self) -> None:
        """Chữ và nút của màn rỗng ở khung phải; nút “Tìm máy mới” chỉ khi đã có trang DISCOVER."""
        title = QCoreApplication.translate("MainWindow", "Ghép đôi máy đầu tiên")
        if self.pages.has_page(Page.DISCOVER):
            text = QCoreApplication.translate(
                "MainWindow", "Mở Teleport trên máy kia, trong cùng mạng với máy này, rồi bấm Tìm máy mới."
            )
            action: str | None = QCoreApplication.translate("MainWindow", "Tìm máy mới")
        else:
            text = QCoreApplication.translate(
                "MainWindow",
                "Mở Teleport trên máy kia, trong cùng mạng với máy này. Máy đó sẽ hiện ở cột bên trái; "
                "bấm vào tên máy để ghép đôi.",
            )
            action = None
        empty = self.empty_state
        empty.set_content("arrow_swap", title, text, action=action)
        empty.title_label.setAccessibleName(title)
        empty.text_label.setAccessibleName(text)
        if action is not None:
            empty.action_button.setAccessibleName(action)

    def _update_paired(self) -> None:
        self._has_paired = self.conversations.model.rowCount() > 0
        self._update_stream()

    def _update_stream(self) -> None:
        """Khung phải: màn rỗng khi RUNNING, chưa có máy đã ghép đôi và luồng chat rỗng."""
        show_empty = self._state is ViewState.RUNNING and not self._has_paired and not self._has_content
        target = self.empty_state if show_empty else self.transfers_area
        if self.stream_pane.currentWidget() is not target:
            self.stream_pane.setCurrentWidget(target)

    def _keep_footer_last(self) -> None:
        """Dời “Mở thư mục” rồi “Đổi…” về cuối chuỗi Tab: widget tạo sau cửa sổ (thẻ lượt truyền,
        trang mới) rơi vào cuối chuỗi, sau hai nút này. Luôn nối “Mở thư mục” → “Đổi…”, kể cả khi
        “Mở thư mục” đang ẩn (Tab tự bỏ qua widget ẩn)."""
        open_button = self.save_bar.open_button
        change_button = self.save_bar.change_button
        footer = (open_button, change_button)
        last = self.previousInFocusChain()
        # `setTabOrder` bỏ qua widget NoFocus: lùi tới widget cuối cùng nhận được tiêu điểm bằng Tab,
        # bỏ qua chính hai nút chân.
        while (
            last is not None
            and last is not self
            and (last in footer or not last.focusPolicy() & Qt.FocusPolicy.TabFocus)
        ):
            last = last.previousInFocusChain()
        if last is not None and last is not self:
            QWidget.setTabOrder(last, open_button)
        QWidget.setTabOrder(open_button, change_button)

    @staticmethod
    def _set_optional(label: QLabel, text: str, accessible_name: str) -> None:
        label.setText(text)
        label.setAccessibleName(accessible_name)
        label.setAccessibleDescription(text)
        label.setVisible(bool(text))

    # ---- Bố cục ------------------------------------------------------------------------------

    def _apply_compact(self) -> None:
        """Bề ngang cột trái theo cửa sổ; dạng thu gọn / đầy đủ chỉ đổi khi trạng thái đổi thật.

        Thu gọn: danh sách chỉ còn avatar, đầu cột xếp dọc và căn giữa (ẩn tên app), lề hẹp,
        `compact_machine` thay `machine_card`. Tiêu điểm đang ở widget sắp ẩn thì chuyển sang widget
        tương ứng của dạng mới (spec B2 mục 2.6, 12.15)."""
        compact = self.sidebar_compact
        width = SIDEBAR_COMPACT_WIDTH if compact else SIDEBAR_WIDTH
        if self.sidebar.width() != width or self.sidebar.minimumWidth() != width:
            self.sidebar.setFixedWidth(width)
        if compact == self._compact_applied:
            return
        self._compact_applied = compact
        focus = self.focusWidget()
        self.conversations.set_compact(compact)
        direction = QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
        self.header_layout.setDirection(direction)
        self.header_buttons.setDirection(direction)
        align = Qt.AlignmentFlag.AlignHCenter if compact else Qt.AlignmentFlag.AlignVCenter
        self.header_layout.setAlignment(self.brand_logo, align)
        self.header_layout.setAlignment(self.header_buttons, align)
        for button in (self.discover_button, self.settings_button):
            self.header_buttons.setAlignment(button, align)
        self.header_layout.setContentsMargins(*(_HEADER_COMPACT_MARGINS if compact else _HEADER_MARGINS))
        self.brand_label.setVisible(not compact)
        self._content_layout.setContentsMargins(*(_CONTENT_COMPACT_MARGINS if compact else _CONTENT_MARGINS))
        self.machine_card.setVisible(not compact)
        self.compact_footer.setVisible(compact)
        self.compact_machine.setVisible(compact)
        self._move_focus_after_compact(focus, compact)

    def _move_focus_after_compact(self, focus: QWidget | None, compact: bool) -> None:
        if focus is None or not isValid(focus):
            return
        if compact and focus in (self.name_label, self.address_label, self.copy_button):
            self.compact_machine.setFocus(Qt.FocusReason.OtherFocusReason)
        elif not compact and focus is self.compact_machine:
            for target in (self.name_label, self.copy_button):
                if target.isVisibleTo(self):
                    target.setFocus(Qt.FocusReason.OtherFocusReason)
                    return
            conversations = self.conversations
            fallback = (
                conversations.list_view
                if conversations.list_view.isVisibleTo(self)
                else conversations.add_button
            )
            fallback.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_conversation_current(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """Hàng hiện hành đổi bằng bàn phím (hay bằng code): cuộn cột trái tới hàng đó."""
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton or not current.isValid():
            return
        self._scroll_to_row(current)

    def _scroll_to_row(self, index: QModelIndex) -> bool:
        inner = self.sidebar_scroll.widget()
        view = self.conversations.list_view
        if inner is None or not view.isVisibleTo(self):
            return False
        rect = view.row_rect(index)
        if rect.isEmpty():
            return False
        center = view.viewport().mapTo(inner, rect.center())
        margin = self.conversations.delegate.row_height() // 2 + theme.SPACING[1]
        self.sidebar_scroll.ensureVisible(center.x(), center.y(), 0, margin)
        return True

    def _on_focus_changed(self, _old: QWidget | None, new: QWidget | None) -> None:
        """Tiêu điểm vào một widget trong vùng cuộn (kể cả đặt bằng code) → cuộn tới nó."""
        if new is None or not isValid(self) or new.window() is not self:
            return
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return  # bấm chuột: widget đã thấy được; cuộn lúc nhấn làm cú bấm rơi sang chỗ khác
        if self._scroll_into_view(new):
            # Widget vừa hiện (khung nhập IP) chưa có vị trí thật tới khi layout chạy: cuộn lại sau đó.
            self._scroll_target = new
            QTimer.singleShot(0, self._scroll_pending)

    def _scroll_pending(self) -> None:
        target, self._scroll_target = self._scroll_target, None
        if target is None or not isValid(self) or not isValid(target) or not target.hasFocus():
            return
        # Hàng nút đổi hướng và nhãn xuống dòng làm layout chạy vài lượt: chạy tới khi khoảng cuộn đứng yên.
        bars = (self.sidebar_scroll.verticalScrollBar(), self.start_view.start_scroll.verticalScrollBar())
        for _ in range(_LAYOUT_PASSES):
            before = [bar.maximum() for bar in bars]
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
            if [bar.maximum() for bar in bars] == before:
                break
        self._scroll_into_view(target)

    def _scroll_into_view(self, widget: QWidget) -> bool:
        view = self.conversations.list_view
        if widget is view and view.currentIndex().isValid():
            # Danh sách cao hơn vùng thấy: cuộn tới hàng hiện hành, không tới giữa danh sách.
            return self._scroll_to_row(view.currentIndex())
        for scroll in (self.sidebar_scroll, self.start_view.start_scroll):
            inner = scroll.widget()
            if inner is not None and inner.isAncestorOf(widget):
                # Cả widget, không chỉ con trỏ chữ như `ensureWidgetVisible` (ô nhập bị che mép dưới);
                # widget cao hơn vùng thấy thì căn giữa nó.
                center = widget.mapTo(inner, widget.rect().center())
                half = scroll.viewport().height() // 2
                scroll.ensureVisible(
                    center.x(), center.y(), 0, min(widget.height() // 2 + theme.SPACING[1], half)
                )
                return True
        return False

    # ---- Sự kiện -----------------------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_compact()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._shown_once = True
        self._apply_compact()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        kind = event.type()
        if kind == QEvent.Type.LanguageChange:
            self.retranslate()
        elif kind in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.start_view.refresh_icon()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        if Tray.is_available():
            self.hide()
            self.hidden_to_tray.emit()
        else:
            self.quit_requested.emit()

    def _submit_first_run(self) -> None:
        """“Bắt đầu” hay Enter trong ô tên: kiểm form; hợp lệ thì phát `start_requested(choice)`."""
        if self._state is not ViewState.WELCOME:
            return
        choice = self.first_run.validate()
        if choice is not None:
            self.start_requested.emit(choice)

    def _retry_shortcut(self) -> None:
        if self.retry_button.isVisibleTo(self):
            self.retry_requested.emit()

    # ---- Phím tắt (`ui.shortcuts`) -------------------------------------------------------------

    def _install_shortcuts(self) -> None:
        """Dựng các `QAction` phím tắt của cửa sổ (danh sách phím ở `ui.shortcuts`)."""
        make = shortcuts.make_action
        self._retry_action = make(self, Shortcut.RETRY, self._retry_shortcut)
        self._close_action = make(self, Shortcut.CLOSE_WINDOW, self.close)
        self._quit_action = make(self, Shortcut.QUIT, self.quit_requested.emit)
        self._back_action = make(self, Shortcut.BACK, self.go_back)
        self._back_action.setEnabled(False)
        self._settings_action = make(self, Shortcut.SETTINGS, self._open_settings)
        self._discover_action = make(self, Shortcut.DISCOVER, self._open_discover)
        self._open_dir_action = make(self, Shortcut.OPEN_RECEIVE_DIR, self._open_receive_dir_shortcut)
        self._conversation_actions: list[QAction] = [
            make(
                self,
                Shortcut.GO_TO_CONVERSATION,
                functools.partial(self._go_to_conversation, row),
                keys=[key],
            )
            for row, key in enumerate(shortcuts.sequences(Shortcut.GO_TO_CONVERSATION))
        ]
        self._previous_action = make(
            self, Shortcut.PREVIOUS_CONVERSATION, lambda: self._step_conversation(-1), auto_repeat=True
        )
        self._next_action = make(
            self, Shortcut.NEXT_CONVERSATION, lambda: self._step_conversation(1), auto_repeat=True
        )
        self._shortcuts_ready = True

    def _update_shortcuts(self) -> None:
        """Bật/tắt phím tắt theo `ViewState`, trang hiện tại và thư mục nhận (xem docstring module)."""
        if not self._shortcuts_ready:
            return  # đang dựng cửa sổ: `_install_shortcuts` chưa chạy xong
        running = self._state is ViewState.RUNNING
        page = self.pages.current_page
        home = running and page is Page.HOME
        self._back_action.setEnabled(page is not Page.HOME)
        self._discover_action.setEnabled(running and self.pages.has_page(Page.DISCOVER))
        self._settings_action.setEnabled(running and self.pages.has_page(Page.SETTINGS))
        self._open_dir_action.setEnabled(running and self._receive_dir is not None)
        for action in (*self._conversation_actions, self._previous_action, self._next_action):
            action.setEnabled(home)

    def open_conversation_at(self, row: int) -> bool:
        """Mở cuộc trò chuyện ở hàng `row` (0 là hàng đầu) của danh sách như `open_conversation`;
        không có hàng đó → False."""
        device_id = self.conversations.device_id_at(row)
        return device_id is not None and self.open_conversation(device_id)

    def step_conversation(self, step: int) -> bool:
        """Mở cuộc trò chuyện cách máy đang chọn `step` hàng (âm: lên trên), không vòng; chưa chọn
        máy nào thì hàng đầu (`step` > 0) hay hàng cuối (`step` < 0). Ra ngoài danh sách → False."""
        device_id = self.conversations.neighbor_id(step)
        return device_id is not None and self.open_conversation(device_id)

    def _go_to_conversation(self, row: int) -> None:
        if self._state is ViewState.RUNNING and self.pages.current_page is Page.HOME:
            self.open_conversation_at(row)

    def _step_conversation(self, step: int) -> None:
        if self._state is ViewState.RUNNING and self.pages.current_page is Page.HOME:
            self.step_conversation(step)

    def _open_receive_dir_shortcut(self) -> None:
        if self._state is ViewState.RUNNING and self._receive_dir is not None:
            self.open_receive_dir_requested.emit(self._receive_dir)
