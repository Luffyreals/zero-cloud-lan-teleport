"""Câu chữ dùng chung của giao diện: lỗi khởi động (E1–E6, M2), M4, M5 trong spec P4-3.

M3 (máy chưa có danh tính) đã bỏ: thay bằng màn lần chạy đầu (mvp F1, spec D1; form ở
`ui.first_run`, hiện ở trạng thái WELCOME của `ui.main_window`). M6 (hộp hỏi nhận file) nằm ở
`ui.offer`. Câu chữ riêng của một màn hình nằm ở module của màn hình đó (ví dụ `ui.radar`,
`ui.transfers_view`).

Chuỗi nguồn tiếng Việt, mọi chuỗi qua `QCoreApplication.translate` với ngữ cảnh `Texts`, gọi lúc
dùng (không lúc import) để đổi ngôn ngữ có hiệu lực ngay. Chuỗi nguồn luôn là literal để bộ trích
`packaging/i18n/update.py` (đọc bằng `ast`) thấy được; số đếm dùng `%n` (luật: `CONTRIBUTING.md`, mục
Bản dịch).

Số hiện cho người dùng (`format_size`, `percent`, `format_duration`, `decimal`) là bản giao diện của
`core.display`: dấu thập phân và đơn vị đếm qua bản dịch, tiếng Việt ra đúng chữ của `core`.

`Text` là chuỗi đã dịch hoặc hàm dựng câu; `resolve` trả ra chuỗi. Thông báo còn hiện khi người dùng
đổi ngôn ngữ nhận hàm, để câu được dịch lại.

Chèn giá trị bằng `fill` (một lượt, chỉ thay `{tên}` có trong bản dịch): bản dịch có ngoặc nhọn
lạ không làm hỏng câu, và chữ do máy kia đặt chứa `{size}` không bị thay tiếp. Chữ từ máy khác
đi qua `peer_label` / `file_label` (`core.display`) trước khi chèn.

Tên lệnh CLI trong câu của GUI nằm trong ngoặc kép “…” (không dùng backtick như ở CLI).

`APP_NAME` là tên hiển thị của sản phẩm (tiêu đề cửa sổ, kèm % tổng khi đang truyền qua
`window_title`; chữ cạnh logo, khay, tiêu đề bóng thoại, hộp
lỗi khởi động, tên đăng ký cho AppUserModelID ở `ui.app`): tên riêng nên không dịch. Trong câu chữ,
“Teleport” vẫn là cách gọi tắt.
"""

from __future__ import annotations

import math
import re
import sys
import unicodedata
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication

from teleport.core.display import display_filename, display_name
from teleport.core.display import format_size as core_format_size

APP_NAME = "ZCL Teleport"  # tên ngắn của “Zero-Cloud LAN Teleport”

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_REPLACEMENT = "�"  # U+FFFD thay ký tự điều khiển, như `cli._printable`


# Chữ của một thông báo: chuỗi đã dịch sẵn, hoặc hàm dựng lại câu theo ngôn ngữ đang dùng. Thông báo
# nhận hàm thì dịch lại khi đổi ngôn ngữ; nhận chuỗi thì bị ẩn khi đổi ngôn ngữ (`widgets.InfoBar`,
# `chat.ChatView.show_notice`), để không còn câu của ngôn ngữ cũ.
Text = str | Callable[[], str]


def resolve(text: Text) -> str:
    """Chữ để hiện của `text` (gọi hàm nếu là hàm)."""
    return text() if callable(text) else text


def fill(template: str, **values: str) -> str:
    """Thay `{tên}` trong `template` bằng `values[tên]` trong một lượt; tên lạ giữ nguyên."""
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def _printable(text: str) -> str:
    return "".join(_REPLACEMENT if unicodedata.category(ch) == "Cc" else ch for ch in text)


def peer_label(name: str | None, device_id: str) -> str:
    """Tên máy kia để hiện (không ngoặc): `display_name`; không có tên thì 8 ký tự đầu của mã."""
    return display_name(_printable(name)) if name else _printable(device_id[:8])


def file_label(name: str) -> str:
    """Tên file để hiện: ký tự điều khiển thành U+FFFD, rồi `display_filename`."""
    return display_filename(_printable(name))


# ---- Số, dung lượng, thời gian -------------------------------------------------------------
# Bản giao diện của `core.display.format_size` / `format_duration`: cùng cách tính, nhưng dấu thập
# phân và đơn vị đếm được qua bản dịch. Tiếng Việt ra đúng chữ của `core` (CLI vẫn dùng `core`).


def decimal(tenths: int) -> str:
    """Số có một chữ số thập phân từ số phần mười ≥ 0: 21 → “2,1” (English “2.1”)."""
    whole, tenth = divmod(tenths, 10)
    template = QCoreApplication.translate("Texts", "{whole},{tenth}", "số có một chữ số thập phân, ví dụ 2,1")
    return fill(template, whole=str(whole), tenth=str(tenth))


def format_size(size: int, *, trim: bool = False) -> str:
    """Như `core.display.format_size` (“512 byte”, “2,1 MB”, `trim` bỏ “,0”), qua bản dịch: English
    “512 bytes”, “1 byte”, “2.1 MB”. Lỗi kiểu / giá trị âm như `core`."""
    text = core_format_size(size, trim=trim)
    number, unit = text.rsplit(" ", 1)
    if unit == "byte":
        return QCoreApplication.translate("Texts", "%n byte", None, size)
    whole, sep, tenth = number.partition(",")
    if sep:
        number = decimal(int(whole) * 10 + int(tenth))
    return f"{number} {unit}"


def percent(tenths: int) -> str:
    """Phần trăm có một chữ số thập phân từ số phần nghìn: 420 → “42,0%” (English “42.0%”)."""
    return f"{decimal(tenths)}%"


def _duration_unit(seconds: int, count: int) -> str:
    """`count` đơn vị cỡ `seconds` giây (86400, 3600, 60, 1), qua bản dịch số đếm."""
    t = QCoreApplication.translate
    if seconds == 86400:
        return t("Texts", "%n ngày", None, count)
    if seconds == 3600:
        return t("Texts", "%n giờ", None, count)
    if seconds == 60:
        return t("Texts", "%n phút", None, count)
    return t("Texts", "%n giây", None, count)


def format_duration(seconds: float) -> str:
    """Như `core.display.format_duration` (cùng cách làm tròn, hai đơn vị lớn nhất, bỏ đơn vị sau khi
    bằng 0), đơn vị qua bản dịch: tiếng Việt “2 phút 10 giây”, English “2 min 10 sec”. `seconds` hữu
    hạn (không thì ValueError, như core); âm tính là 0."""
    if not math.isfinite(seconds):
        raise ValueError("seconds phải hữu hạn")
    total = max(0, math.floor(seconds + 0.5))
    for size, small in ((86400, 3600), (3600, 60), (60, 1)):
        if total >= size:
            major, rest = divmod(total, size)
            minor = rest // small
            if minor == 0:
                return _duration_unit(size, major)
            return f"{_duration_unit(size, major)} {_duration_unit(small, minor)}"
    return _duration_unit(1, total)


# ---- Lỗi khởi động node --------------------------------------------------------------------


def start_error(code: str, detail: str = "") -> tuple[str, list[str]]:
    """(câu chính, các câu gợi ý) cho mã `bridge.StartError`; mã lạ dùng câu của OTHER.

    `detail` theo `bridge.classify_start_error`: CONFIG_DIR là `<đường dẫn>\\n<lỗi>`, RECEIVE_DIR
    là đường dẫn, PORT là lỗi của hệ điều hành.

    E4 (RECEIVE_DIR) chỉ còn cho `NodeOptions.receive_dir` là đường dẫn tường minh (test): giao diện
    chạy node với thư mục đã lưu, hỏng thì node vẫn chạy mà không nhận file (`ui.receive_dir`).
    """
    t = QCoreApplication.translate
    if code == "locked":  # M2
        return (
            t(
                "Texts",
                "Teleport đang chạy ở nơi khác với thư mục cấu hình này "
                "(ví dụ lệnh “teleport receive” trong cửa sổ dòng lệnh).",
            ),
            [t("Texts", "Hãy dừng nó rồi bấm Thử lại.")],
        )
    if code == "config_dir":  # E1
        path, _, error = detail.partition("\n")
        if error:
            head = fill(
                t("Texts", "Không dùng được thư mục cấu hình {path} ({error})."), path=path, error=error
            )
        else:
            head = fill(t("Texts", "Không dùng được thư mục cấu hình {path}."), path=path)
        return head, [t("Texts", "Hãy kiểm tra quyền ghi vào thư mục đó rồi bấm Thử lại.")]
    if code == "identity":  # E2: câu mvp mục 8 cho danh tính hỏng
        return (
            t(
                "Texts",
                "Không đọc được danh tính của máy này. "
                "Teleport sẽ không tự tạo danh tính mới để khỏi mất các ghép đôi.",
            ),
            [t("Texts", "Hãy chạy “teleport identity” trong cửa sổ dòng lệnh để xem chi tiết.")],
        )
    if code == "trust_store":  # E3
        return (
            t(
                "Texts",
                "Không đọc được danh sách thiết bị đã ghép đôi. "
                "Teleport sẽ không tự xóa nó để khỏi mất các ghép đôi.",
            ),
            [t("Texts", "Hãy chạy “teleport receive” trong cửa sổ dòng lệnh để xem chi tiết.")],
        )
    if code == "receive_dir":  # E4
        return (
            fill(t("Texts", "Không dùng được thư mục nhận {path}."), path=detail),
            [t("Texts", "Hãy kiểm tra ổ đĩa và quyền ghi rồi bấm Thử lại.")],
        )
    if code == "port":  # E5
        return (
            fill(t("Texts", "Không mở được cổng để nhận kết nối ({error})."), error=detail),
            [t("Texts", "Hãy đóng ứng dụng đang dùng cổng đó rồi bấm Thử lại.")],
        )
    return (  # E6
        t("Texts", "Teleport không khởi động được vì một lỗi không mong đợi."),
        [
            t(
                "Texts",
                "Hãy bấm Thử lại; nếu vẫn lỗi, hãy chạy “teleport receive” "
                "trong cửa sổ dòng lệnh để xem chi tiết.",
            )
        ],
    )


def config_dir_unusable_at_launch(detail: str) -> tuple[str, list[str]]:
    """E1 khi chưa có cửa sổ (không lấy được `gui.lock`): hộp chỉ có nút OK nên không nói "Thử lại"."""
    head, _ = start_error("config_dir", detail)
    t = QCoreApplication.translate
    return head, [t("Texts", "Hãy kiểm tra quyền ghi vào thư mục đó rồi mở lại Teleport.")]


def not_responding() -> tuple[str, list[str]]:
    """Bản Teleport khác giữ `gui.lock` mà không trả lời lệnh `show` (thường là đang tắt)."""
    t = QCoreApplication.translate
    return (
        t("Texts", "Teleport đang tắt hoặc chưa phản hồi."),
        [t("Texts", "Hãy thử lại sau giây lát.")],
    )


# ---- Cửa sổ, khay --------------------------------------------------------------------------


def window_title(percent: int | None) -> str:
    """Tiêu đề cửa sổ chính: `APP_NAME`, hay “60% · ZCL Teleport” khi đang truyền (`ui.progress`).

    `percent` kẹp trong 0…100; None → chỉ `APP_NAME`."""
    if percent is None:
        return APP_NAME
    value = min(100, max(0, int(percent)))
    template = QCoreApplication.translate("Texts", "{percent}% · {app}")
    return fill(template, percent=str(value), app=APP_NAME)


def still_running() -> str:
    """M4: bóng thoại khi đóng cửa sổ lần đầu trong phiên."""
    return QCoreApplication.translate(
        "Texts",
        "Teleport vẫn chạy ở khay hệ thống và vẫn nhận file. Chọn Thoát trong menu khay để tắt hẳn.",
    )


def still_running_paused() -> str:
    """M4 khi người dùng đang tạm dừng nhận (menu khay, spec D4 mục 14.12)."""
    return QCoreApplication.translate(
        "Texts",
        "Teleport vẫn chạy ở khay hệ thống nhưng đang tạm dừng nhận file mới và clipboard. "
        "Chọn Thoát trong menu khay để tắt hẳn.",
    )


def menu_open() -> str:
    return QCoreApplication.translate("Texts", "Mở Teleport")


def menu_send() -> str:
    return QCoreApplication.translate("Texts", "Gửi file…")


def menu_pause() -> str:
    return QCoreApplication.translate("Texts", "Tạm dừng nhận")


def menu_quit() -> str:
    return QCoreApplication.translate("Texts", "Thoát")


def retry() -> str:
    """Nút “Thử lại” (phím tắt ở `ui.shortcuts`)."""
    return QCoreApplication.translate("Texts", "Thử lại")


def file_manager_name() -> str:
    """Tên trình quản lý file của hệ điều hành đang chạy (câu về dán file đã chép): Windows
    “File Explorer”, macOS “Finder” (tên riêng, không dịch), khác “trình quản lý file”."""
    if sys.platform.startswith("win"):
        return "File Explorer"
    if sys.platform == "darwin":
        return "Finder"
    return QCoreApplication.translate("Texts", "trình quản lý file")


# ---- Nhận file -----------------------------------------------------------------------------


def offer_waiting() -> str:
    """Bóng thoại của khay khi có `offer` đang chờ trả lời."""
    return QCoreApplication.translate("Texts", "Có file đang chờ bạn nhận.")


# ---- Máy này, thiết bị ---------------------------------------------------------------------

_OS_LABELS = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}  # tên riêng: không dịch


def device_name_notice() -> str:
    """Câu mvp F1 về tên thiết bị (nguyên văn): tên máy này hiện với mọi máy trong mạng."""
    return QCoreApplication.translate(
        "Texts",
        "Tên này hiện với mọi máy trong cùng mạng, kể cả máy lạ chưa ghép đôi. "
        "Nếu không muốn lộ tên mình, hãy đặt tên khác.",
    )


def os_label(code: str | None) -> str | None:
    """Tên hệ điều hành để hiện (`windows` → “Windows”); mã lạ hay None → None (không hiện)."""
    return _OS_LABELS.get(code or "")
