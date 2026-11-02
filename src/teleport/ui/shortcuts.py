"""Phím tắt của cửa sổ chính: nguồn duy nhất của danh sách phím (mvp N12, F4, F10; “phím tắt và dán file”).

`SHORTCUTS` liệt kê mọi phím theo thứ tự hàng của bảng “Phím tắt” trong Cài đặt ▸ Nâng cao. `QAction`
(`make_action`), tooltip của nút (`sequence`, `key_text`) và bảng (`table_rows`) đều đọc từ đây: không
module nào khác viết cứng chuỗi phím. Nơi gắn và điều kiện bật của từng phím nằm ở module dùng nó
(`ui.main_window`: các phím của cửa sổ; `ui.chat`: chọn file, dán file).

Mỗi `ShortcutInfo.keys` là chuỗi `PortableText` (“Ctrl+N”) hay một `QKeySequence.StandardKey`
(Paste: Ctrl+V và Shift+Ins trên Windows). StandardKey chỉ được đổi ra phím lúc gọi `sequences`
(cần `QGuiApplication`), không lúc import. `GO_TO_CONVERSATION` có chín phím (Ctrl+1 … Ctrl+9), mỗi
phím một `QAction`; trong bảng ghi gọn “Ctrl+1 đến Ctrl+9”. Bảng chỉ ghi phím đầu của mỗi mục (không
ghi Shift+Ins).

Luật chọn phím: không phím nào dùng Ctrl+Alt hay AltGr (trình đọc màn hình, bàn phím có AltGr);
không trùng phím soạn thảo chuẩn của ô nhập, trừ Paste (ô nhập sửa được tự nhận `ShortcutOverride`
nên Ctrl+V trong ô nhập vẫn dán chữ). Mọi `QAction` là `WindowShortcut` (hộp thoại là cửa sổ riêng
nên không bị bắt phím) và không tự lặp khi giữ phím, trừ hai phím chuyển cuộc trò chuyện.

Mô tả dịch lúc gọi, ngữ cảnh `"Shortcuts"`; tên phím theo `QKeySequence.NativeText` (Qt viết tên phím
bằng tiếng Anh: Up, Down, Esc). `retranslate_actions` đặt lại chữ của các `QAction` (nhận ra qua
`data()` là giá trị `Shortcut`). Không import `ui.widgets` (widgets dùng module này).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

from teleport.ui import texts


class Shortcut(StrEnum):
    """Mã của một phím tắt (giá trị nằm trong `QAction.data()`)."""

    DISCOVER = "discover"
    SETTINGS = "settings"
    OPEN_RECEIVE_DIR = "open_receive_dir"
    GO_TO_CONVERSATION = "go_to_conversation"
    PREVIOUS_CONVERSATION = "previous_conversation"
    NEXT_CONVERSATION = "next_conversation"
    PICK_FILES = "pick_files"
    PASTE_FILES = "paste_files"
    BACK = "back"
    CLOSE_WINDOW = "close_window"
    QUIT = "quit"
    RETRY = "retry"


@dataclass(frozen=True, slots=True)
class ShortcutInfo:
    """Một mục của bảng phím: mã, các phím (PortableText hay StandardKey), mô tả (dịch lúc gọi)."""

    id: Shortcut
    keys: tuple[str | QKeySequence.StandardKey, ...]
    describe: Callable[[], str]


SHORTCUTS: tuple[ShortcutInfo, ...] = (
    ShortcutInfo(
        Shortcut.DISCOVER, ("Ctrl+N",), lambda: QCoreApplication.translate("Shortcuts", "Tìm máy mới")
    ),
    ShortcutInfo(
        Shortcut.SETTINGS, ("Ctrl+,",), lambda: QCoreApplication.translate("Shortcuts", "Mở Cài đặt")
    ),
    ShortcutInfo(
        Shortcut.OPEN_RECEIVE_DIR,
        ("Ctrl+Shift+E",),
        lambda: QCoreApplication.translate("Shortcuts", "Mở thư mục nhận"),
    ),
    ShortcutInfo(
        Shortcut.GO_TO_CONVERSATION,
        tuple(f"Ctrl+{n}" for n in range(1, 10)),
        lambda: QCoreApplication.translate("Shortcuts", "Mở cuộc trò chuyện thứ 1 đến 9 trong danh sách"),
    ),
    ShortcutInfo(
        Shortcut.PREVIOUS_CONVERSATION,
        ("Alt+Up",),
        lambda: QCoreApplication.translate("Shortcuts", "Chuyển lên cuộc trò chuyện phía trên"),
    ),
    ShortcutInfo(
        Shortcut.NEXT_CONVERSATION,
        ("Alt+Down",),
        lambda: QCoreApplication.translate("Shortcuts", "Chuyển xuống cuộc trò chuyện phía dưới"),
    ),
    ShortcutInfo(
        Shortcut.PICK_FILES, ("Ctrl+O",), lambda: QCoreApplication.translate("Shortcuts", "Chọn file để gửi")
    ),
    ShortcutInfo(
        Shortcut.PASTE_FILES,
        (QKeySequence.StandardKey.Paste,),
        lambda: texts.fill(
            QCoreApplication.translate("Shortcuts", "Gửi file đã chép trong {file_manager}"),
            file_manager=texts.file_manager_name(),
        ),
    ),
    ShortcutInfo(Shortcut.BACK, ("Esc",), lambda: QCoreApplication.translate("Shortcuts", "Quay lại")),
    ShortcutInfo(
        Shortcut.CLOSE_WINDOW, ("Ctrl+W",), lambda: QCoreApplication.translate("Shortcuts", "Đóng cửa sổ")
    ),
    ShortcutInfo(
        Shortcut.QUIT, ("Ctrl+Q",), lambda: QCoreApplication.translate("Shortcuts", "Thoát Teleport")
    ),
    ShortcutInfo(
        Shortcut.RETRY,
        ("F5",),
        lambda: QCoreApplication.translate("Shortcuts", "Thử lại khi Teleport không khởi động được"),
    ),
)

_BY_ID: dict[Shortcut, ShortcutInfo] = {entry.id: entry for entry in SHORTCUTS}
_NATIVE = QKeySequence.SequenceFormat.NativeText
_PORTABLE = QKeySequence.SequenceFormat.PortableText


def info(id: Shortcut) -> ShortcutInfo:
    """Mục của `id` (mã lạ → KeyError)."""
    return _BY_ID[Shortcut(id)]


def sequences(id: Shortcut) -> list[QKeySequence]:
    """Mọi phím của `id`, theo thứ tự; StandardKey đổi ra phím của hệ điều hành đang chạy (lúc gọi)."""
    result: list[QKeySequence] = []
    for key in info(id).keys:
        if isinstance(key, QKeySequence.StandardKey):
            result.extend(seq for seq in QKeySequence.keyBindings(key) if not seq.isEmpty())
        else:
            result.append(QKeySequence(key))
    return result


def sequence(id: Shortcut) -> QKeySequence:
    """Phím đầu tiên của `id` (rỗng khi hệ điều hành không có phím cho StandardKey đó)."""
    found = sequences(id)
    return found[0] if found else QKeySequence()


def portable_text(id: Shortcut) -> str:
    """Phím đầu tiên của `id` dạng PortableText (“Ctrl+,”)."""
    return sequence(id).toString(_PORTABLE)


def key_text(id: Shortcut) -> str:
    """Tên phím để hiện (NativeText); `GO_TO_CONVERSATION` → “Ctrl+1 đến Ctrl+9”."""
    found = sequences(id)
    if not found:
        return ""
    if len(found) > 1 and Shortcut(id) is Shortcut.GO_TO_CONVERSATION:
        return texts.fill(
            QCoreApplication.translate("Shortcuts", "{first} đến {last}"),
            first=found[0].toString(_NATIVE),
            last=found[-1].toString(_NATIVE),
        )
    return found[0].toString(_NATIVE)


def describe(id: Shortcut) -> str:
    """Mô tả của `id` theo ngôn ngữ đang dùng."""
    return info(id).describe()


def make_action(
    parent: QWidget,
    id: Shortcut,
    slot: Callable[[], object],
    *,
    keys: Sequence[QKeySequence] | None = None,
    auto_repeat: bool = False,
) -> QAction:
    """`QAction` `WindowShortcut` của `id` gắn vào `parent`: phím là `keys` (mặc định mọi phím của
    `id`), chữ là mô tả, `data()` là giá trị của `id`; bấm phím thì gọi `slot()`."""
    action = QAction(parent)
    action.setShortcuts(list(keys) if keys is not None else sequences(id))
    action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    action.setAutoRepeat(auto_repeat)
    action.setText(describe(id))
    action.setData(str(Shortcut(id)))
    action.triggered.connect(lambda *_args: slot())
    parent.addAction(action)
    return action


def retranslate_actions(widget: QWidget) -> None:
    """Đặt lại chữ của các `QAction` của `widget` có `data()` là một `Shortcut`."""
    values = {str(entry.id) for entry in SHORTCUTS}
    for action in widget.actions():
        data = action.data()
        if isinstance(data, str) and data in values:
            action.setText(describe(Shortcut(data)))


def table_rows() -> list[tuple[str, str]]:
    """(mô tả, tên phím) của mọi mục theo thứ tự `SHORTCUTS` (bảng trong Cài đặt)."""
    return [(entry.describe(), key_text(entry.id)) for entry in SHORTCUTS]
