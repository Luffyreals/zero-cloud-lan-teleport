"""Lời mời nhận file phía giao diện (mvp F4, mục 7.3, mục 8, N12; spec B4 mục 3.2, 3.4).

Hai phần:

**`OfferBook`**: nguồn sự thật duy nhất của các lời mời (`OfferReceived` chưa tự nhận) trên luồng Qt.
Hộp hỏi (`OfferPrompts`) và bong bóng lời mời (`ui.chat_bubbles.OfferPanel`) chỉ phát *ý định*; mọi
quyết định đi qua `OfferBook.answer`, và `answered(key, accept, always)` phát **đúng một lần** mỗi
offer. Máy trạng thái của một offer:

    (không có) --add(OfferReceived, auto_accepted=False)--> PENDING
    PENDING  --answer(k, a)--> ANSWERED   [changed, rồi answered(k, a, always)]
    PENDING  --finish(k)--> (gỡ)          [removed; KHÔNG answered]
    ANSWERED --finish(k)--> (gỡ)          [removed]
    *        --clear()-->   (gỡ)          [removed từng key; KHÔNG answered]

`add` trả False khi `auto_accepted`, khi key đã có (ở bất kỳ pha nào: một `OfferReceived` lặp lại hay
tới muộn không mở lại hộp), hay khi không phải chiều RECEIVE. `answer` chỉ đổi khi PENDING; mọi lời
gọi đều ở luồng Qt nên hai cú bấm gần như cùng lúc (hộp và bong bóng, Esc ngay sau Nhận) bị xếp tuần
tự và lần đầu thắng. Lý do phải chặn ở đây: engine vẫn từ chối ngay `decide(False)` tới sau
`decide(True)` khi đang kiểm lại chỗ trống (`core/transfer.py`). Entry ANSWERED chỉ gỡ khi có
`TransferFinished`; trần an toàn `OFFER_BOOK_MAX` entry, vượt thì gỡ entry ANSWERED cũ nhất (không
bao giờ gỡ PENDING; số PENDING bị chặn bởi số máy đã ghép đôi, protocol §3.4).

**`OfferPrompts`**: hộp hỏi nhận file, mỗi `TransferKey` một `QDialog` không cha, `NonModal`,
`WA_DeleteOnClose`, mở bằng `show()` + `raise_()` + `activateWindow()` (không `exec()`). Việc mở do
`ui.transfers.TransfersController` quyết định (`show_prompt`); tối đa `PROMPTS_MAX_OPEN` hộp cùng lúc,
thêm thì xếp hàng FIFO và mở dần khi một hộp đóng (chỉ key còn PENDING). Hộp nghe book: ANSWERED hay
`removed` thì đóng, không phát gì; `always` / `connected` đổi thì cập nhật ô tick (chặn signal) và
dòng mất kết nối. Bố cục từ trên xuống (mvp 7.3):

1. câu đầu chữ lớn, đậm (đặt bằng font, không HTML): ““X” muốn gửi n file (cỡ) tới máy này.”;
2. danh sách file: tối đa `LIST_MAX` dòng “tên  cỡ”, rồi “… và k file khác” (chỉ dựng chữ cho
   `LIST_MAX` tên đầu, nên `offer` 1000 file vẫn nhanh);
3. dòng mất kết nối (`tone=muted`), chỉ khi máy gửi mất kết nối điều khiển;
4. “Lưu vào: …” (đang đổi thì “Đang đổi sang …”) kèm nút “Đổi…” (`offerChangeDir`, ẩn khi chưa có
   thư mục nhận); có lỗi đổi thư mục thì nhãn `tone=warning` ngay dưới (`offerDirError`). Lỗi chỉ
   hiện ở các hộp đang mở lúc `set_dir_error`, không lưu cho hộp mở sau; gỡ khi hộp đóng, khi lần
   đổi kế tiếp bắt đầu (`set_receive_dir_pending` khác None) hay khi `set_dir_error(None)`. Lỗi là
   `texts.Text` (hàm dựng câu thì đổi ngôn ngữ dịch lại). Hộp đang hiện mà chữ hay dòng đổi thì
   `fit_height` nới chiều cao theo heightForWidth (cửa sổ cấp cao không tự cao lên);
5. ô “Luôn nhận từ thiết bị này” (`offerAlways`);
6. “Từ chối” và “Nhận” căn phải; “Nhận” là nút chính (đậm, tô màu nhấn qua `theme.PRIMARY_PROPERTY`).

Thứ tự Tab: Đổi… → ô tick → Từ chối → Nhận; tiêu điểm ban đầu ở “Từ chối”. Nút mặc định (Enter),
Esc và nút X đều là “Từ chối”: nhận file phải là lựa chọn có chủ ý. Đang đổi thư mục nhận
(`set_receive_dir_pending` khác None) thì “Nhận” và “Đổi…” tắt: Nhận lúc node đang mở thư mục mới
sẽ nhận lượt vào thư mục cũ rồi việc đổi báo BUSY. Hộp rộng tối thiểu `theme.DIALOG_MIN_WIDTH`, tối
đa `BOX_MAX_WIDTH`.

Mọi nhãn `Qt.PlainText`; chữ máy kia không vào tooltip. Nhãn có chữ máy kia hay đường dẫn (câu đầu,
danh sách file, dòng mất kết nối, “Lưu vào”, lỗi thư mục; ở bong bóng lời mời cũng vậy) là
`PeerTextLabel`: không ép độ rộng tối thiểu vượt khung (danh sách file của hộp rút gọn từng dòng theo
bề ngang thực, các nhãn khác xuống dòng). Tên máy gửi qua `texts.peer_label`
(`display_name`; không có tên thì 8 ký tự đầu của mã máy), tên file qua `texts.file_label`,
đường dẫn qua `send.printable`. `offer_text` trả toàn bộ chữ của hộp (chữ thuần). Các hàm chữ ở đây
dùng chung với bong bóng lời mời. Chuỗi qua `QCoreApplication.translate("Offer", ...)` lúc dùng; đổi
ngôn ngữ dịch lại chữ đang hiện.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from teleport.app.transfers import Direction, OfferReceived
from teleport.core.transfer import TransferKey
from teleport.ui import texts, theme
from teleport.ui.send import printable
from teleport.ui.texts import fill as _fill

LIST_MAX = 10  # số dòng tên file tối đa (mvp mục 7.3)
PROMPTS_MAX_OPEN = 3  # số hộp hỏi mở cùng lúc; thêm thì xếp hàng FIFO
OFFER_BOOK_MAX = 1024  # trần an toàn số entry của `OfferBook`
_MIN_WIDTH = theme.DIALOG_MIN_WIDTH
BOX_MAX_WIDTH = 2 * theme.DIALOG_MIN_WIDTH  # px, hộp hỏi không rộng hơn (tên máy kia dài bất thường)
PEER_TEXT_MIN_WIDTH = 120  # px, gợi ý rộng tối thiểu của `PeerTextLabel`
PEER_TEXT_MAX_WIDTH = 560  # px, gợi ý rộng tối đa của `PeerTextLabel`


# =================================================================================================
# Hàm chữ (dùng chung với bong bóng lời mời)
# =================================================================================================


def offer_parts(offer: OfferReceived, receive_dir: Path | None) -> tuple[str, list[str], str | None]:
    """(câu đầu, các dòng danh sách file, dòng “Lưu vào” hay None) của hộp hỏi, chữ thuần."""
    t = QCoreApplication.translate
    peer = texts.peer_label(offer.device_name, offer.key.device_id)
    count = len(offer.files)
    head = _fill(
        t("Offer", "“{name}” muốn gửi %n file ({size}) tới máy này.", None, count),
        name=peer,
        size=texts.format_size(max(0, offer.total_bytes)),
    )
    lines = [
        f"{texts.file_label(name)}  {texts.format_size(max(0, entry.size))}"
        for name, entry in zip(offer.names[:LIST_MAX], offer.files[:LIST_MAX], strict=False)
    ]
    rest = count - min(count, LIST_MAX)
    if rest > 0:
        lines.append(more_text(rest))
    return head, lines, save_line(receive_dir, None)


def offer_text(offer: OfferReceived, receive_dir: Path | None, *, always: bool | None = None) -> str:
    """Toàn bộ chữ của hộp hỏi (chữ thuần, nhiều dòng). `always` khác None thì thêm dòng ô tick
    “Luôn nhận từ thiết bị này” (“[x]” / “[ ]”)."""
    head, lines, save = offer_parts(offer, receive_dir)
    out = [head, "", *lines]
    if save is not None:
        out += ["", save]
    if always is not None:
        out += ["", f"[{'x' if always else ' '}] {always_text()}"]
    return "\n".join(out)


def more_text(rest: int) -> str:
    """“… và k file khác” sau `LIST_MAX` tên đầu."""
    return QCoreApplication.translate("Offer", "… và %n file khác", None, max(0, rest))


def save_line(receive_dir: Path | None, pending: Path | None) -> str | None:
    """“Lưu vào: {path}”; đang đổi (`pending`) thì “Đang đổi sang {path}…”; không có gì → None."""
    t = QCoreApplication.translate
    if pending is not None:
        return _fill(t("Offer", "Đang đổi sang {path}…"), path=printable(str(pending)))
    if receive_dir is not None:
        return _fill(t("Offer", "Lưu vào: {path}"), path=printable(str(receive_dir)))
    return None


def change_text() -> str:
    """Nút “Đổi…” cạnh dòng “Lưu vào”."""
    return QCoreApplication.translate("Offer", "Đổi…")


def change_name() -> str:
    """Tên trợ năng của nút “Đổi…”."""
    return QCoreApplication.translate("Offer", "Đổi thư mục nhận")


def always_text() -> str:
    """Ô tick “Luôn nhận từ thiết bị này” (chỉ có hiệu lực khi bấm Nhận, áp cho lượt sau)."""
    return QCoreApplication.translate("Offer", "Luôn nhận từ thiết bị này")


def accept_text() -> str:
    return QCoreApplication.translate("Offer", "Nhận")


def reject_text() -> str:
    return QCoreApplication.translate("Offer", "Từ chối")


def title_text() -> str:
    """Tiêu đề hộp hỏi."""
    return QCoreApplication.translate("Offer", "Có file gửi tới")


def disconnected_text(peer: str) -> str:
    """Dòng mất kết nối với máy gửi; `peer` đã qua `peer_label`."""
    return _fill(
        QCoreApplication.translate(
            "Offer",
            "Mất kết nối với {name}. Bạn vẫn trả lời được; nếu nhận, file sẽ bắt đầu khi hai máy nối lại.",
        ),
        name=peer,
    )


def pending_accept_hint() -> str:
    """Vì sao “Nhận” đang tắt (đang đổi thư mục nhận)."""
    return QCoreApplication.translate("Offer", "Chờ đổi thư mục nhận xong")


def always_save_error_text(peer: str) -> str:
    """mvp mục 8: đã nhận lượt này nhưng không lưu được “Luôn nhận”; `peer` đã qua `peer_label`."""
    return _fill(
        QCoreApplication.translate(
            "Offer",
            "Chưa lưu được “Luôn nhận” cho {name} vì không ghi được cài đặt của Teleport. Hãy thử lại "
            "trong Cài đặt ▸ Thiết bị tin cậy (bỏ chọn “Hỏi trước khi nhận”).",
        ),
        name=peer,
    )


def _peer_of(offer: OfferReceived) -> str:
    return texts.peer_label(offer.device_name, offer.key.device_id)


class PeerTextLabel(QLabel):
    """Nhãn chữ thuần có chữ do máy kia đặt (tên máy, tên file) hay đường dẫn dài, dùng chung với
    bong bóng lời mời.

    Không bao giờ ép độ rộng tối thiểu của khung chứa: tên hợp lệ trên wire vẫn có thể là một cụm
    dấu kết hợp rộng cả nghìn px (review B4). Gợi ý rộng tối thiểu `PEER_TEXT_MIN_WIDTH`, gợi ý rộng
    tối đa `PEER_TEXT_MAX_WIDTH`.

    - `wrap=True`: xuống dòng như `QLabel` (Qt ngắt ở ranh giới từ, từ quá dài thì ngắt ở bất kỳ
      đâu); một cụm ký tự không tách được mà rộng hơn nhãn thì bị cắt ở mép, chữ sau nó vẫn hiện.
    - `wrap=False`: khi vẽ, mỗi dòng được rút gọn giữa (“…”) theo bề ngang thực lúc đó (nên tự đúng
      khi đổi cỡ, đổi font, đổi ngôn ngữ). `text()` (cũng là chữ trình đọc màn hình đọc) vẫn là chữ
      đầy đủ; `shown_text()` là chữ đang vẽ.
    """

    def __init__(self, *, wrap: bool, object_name: str | None = None) -> None:
        super().__init__()
        self._wrap = wrap
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setWordWrap(wrap)
        if object_name is not None:
            self.setObjectName(object_name)

    def shown_text(self) -> str:
        """Chữ đang vẽ: `text()` khi xuống dòng, không thì từng dòng đã rút gọn theo bề ngang."""
        if self._wrap:
            return self.text()
        width = max(0, self.contentsRect().width() - 2 * self.margin())
        metrics = self.fontMetrics()
        return "\n".join(
            line
            if metrics.horizontalAdvance(line) <= width
            else metrics.elidedText(line, Qt.TextElideMode.ElideMiddle, width)
            for line in self.text().split("\n")
        )

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setWidth(min(hint.width(), PEER_TEXT_MAX_WIDTH))
        return hint

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        hint.setWidth(min(hint.width(), PEER_TEXT_MIN_WIDTH))
        return hint

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._wrap:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        try:
            rect = self.contentsRect().adjusted(self.margin(), self.margin(), -self.margin(), -self.margin())
            self.style().drawItemText(
                painter,
                rect,
                int(self.alignment()),
                self.palette(),
                self.isEnabled(),
                self.shown_text(),
                self.foregroundRole(),
            )
        finally:
            painter.end()


# =================================================================================================
# OfferBook
# =================================================================================================


class OfferPhase(StrEnum):
    PENDING = "pending"  # chờ người dùng
    ANSWERED = "answered"  # đã gửi quyết định cho node, chờ TransferFinished / lượt chạy


@dataclass(eq=False)
class OfferEntry:
    """Một lời mời trong `OfferBook`."""

    offer: OfferReceived
    seq: int  # thứ tự tới (tăng dần)
    phase: OfferPhase = OfferPhase.PENDING
    accepted: bool | None = None  # quyết định đã gửi
    always: bool = False  # ô “Luôn nhận từ thiết bị này”
    connected: bool = True  # máy gửi còn kết nối điều khiển

    @property
    def key(self) -> TransferKey:
        return self.offer.key


class OfferBook(QObject):
    """Các lời mời đang chờ hay đã trả lời mà lượt chưa kết thúc (xem docstring module)."""

    added = Signal(object)  # TransferKey
    changed = Signal(object)  # TransferKey: phase / always / connected đổi
    removed = Signal(object)  # TransferKey: lượt kết thúc hay host mới
    answered = Signal(object, bool, bool)  # (key, accept, always): đúng một lần mỗi offer

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: dict[TransferKey, OfferEntry] = {}  # theo thứ tự tới
        self._seq = 0

    def add(self, offer: OfferReceived, *, connected: bool = True) -> bool:
        """Thêm lời mời cần hỏi; False (không làm gì) khi tự nhận, đã có, hay không phải chiều nhận."""
        key = offer.key
        if offer.auto_accepted or key in self._entries or key.direction is not Direction.RECEIVE:
            return False
        if len(self._entries) >= OFFER_BOOK_MAX:
            oldest = next((k for k, e in self._entries.items() if e.phase is OfferPhase.ANSWERED), None)
            if oldest is not None:
                del self._entries[oldest]
                self.removed.emit(oldest)
        self._seq += 1
        self._entries[key] = OfferEntry(offer, self._seq, connected=bool(connected))
        self.added.emit(key)
        return True

    def entry(self, key: TransferKey) -> OfferEntry | None:
        return self._entries.get(key)

    def keys(self) -> list[TransferKey]:
        """Mọi key đang có, theo thứ tự tới."""
        return list(self._entries)

    def pending_keys(self) -> list[TransferKey]:
        """Các key PENDING, theo `seq`."""
        return [k for k, e in self._entries.items() if e.phase is OfferPhase.PENDING]

    def answer(self, key: TransferKey, accept: bool) -> bool:
        """Chốt quyết định: chỉ khi PENDING (True); mọi lần khác False và không phát gì."""
        entry = self._entries.get(key)
        if entry is None or entry.phase is not OfferPhase.PENDING:
            return False
        entry.phase = OfferPhase.ANSWERED
        entry.accepted = bool(accept)
        self.changed.emit(key)
        self.answered.emit(key, entry.accepted, entry.always)
        return True

    def set_always(self, key: TransferKey, on: bool) -> None:
        """Ô “Luôn nhận”: chỉ khi PENDING; không đổi thì không phát."""
        entry = self._entries.get(key)
        if entry is None or entry.phase is not OfferPhase.PENDING or entry.always == bool(on):
            return
        entry.always = bool(on)
        self.changed.emit(key)

    def set_connected(self, device_id: str, connected: bool) -> None:
        """Máy gửi còn hay mất kết nối điều khiển: cập nhật mọi lời mời của máy đó."""
        for key, entry in list(self._entries.items()):
            if key.device_id == device_id and entry.connected != bool(connected):
                entry.connected = bool(connected)
                self.changed.emit(key)

    def finish(self, key: TransferKey) -> None:
        """Lượt kết thúc (`TransferFinished` bất kỳ): gỡ, không quyết định."""
        if self._entries.pop(key, None) is not None:
            self.removed.emit(key)

    def clear(self) -> None:
        """Host mới hay thoát: gỡ mọi lời mời, không quyết định (node tự từ chối khi đóng)."""
        for key in list(self._entries):
            if self._entries.pop(key, None) is not None:
                self.removed.emit(key)


# =================================================================================================
# Hộp hỏi
# =================================================================================================


class _OfferBox(QDialog):
    """Hộp hỏi; gọi `on_language_change` khi nhận `LanguageChange`."""

    def __init__(self, on_language_change: Callable[[], None]) -> None:
        super().__init__()
        self._on_language_change = on_language_change

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self._on_language_change()


class _Prompt:
    """Một hộp hỏi đang mở."""

    def __init__(self, entry: OfferEntry, owner: OfferPrompts) -> None:
        self.entry = entry
        self.offer = entry.offer
        self._owner = owner
        self.resolved = False  # đã có quyết định hoặc đã đóng không quyết định
        self.closed = False
        # Lỗi đổi thư mục xảy ra khi hộp này đang mở (chuỗi hay hàm dựng câu, dịch lại khi đổi ngôn ngữ).
        self.dir_error: texts.Text | None = None
        box = _OfferBox(self.retranslate)
        self.box = box
        box.setObjectName("offerBox")
        box.setWindowModality(Qt.WindowModality.NonModal)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.setMinimumWidth(_MIN_WIDTH)
        box.setMaximumWidth(BOX_MAX_WIDTH)

        self.head_label = PeerTextLabel(wrap=True, object_name="offerHead")
        head_font = self.head_label.font()
        head_font.setBold(True)
        if head_font.pointSizeF() > 0:
            head_font.setPointSizeF(head_font.pointSizeF() * 1.25)
        self.head_label.setFont(head_font)
        self.files_label = PeerTextLabel(wrap=False, object_name="offerFiles")
        self.note_label = PeerTextLabel(wrap=True, object_name="offerDisconnected")
        self.note_label.setProperty(theme.TONE_PROPERTY, "muted")
        self.save_label = PeerTextLabel(wrap=True, object_name="offerSaveTo")
        small = self.save_label.font()
        if small.pointSizeF() > 0:
            small.setPointSizeF(small.pointSizeF() * 0.9)
        self.save_label.setFont(small)
        self.save_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)  # chữ phụ, vẫn ≥ 4,5:1
        self.change_button = QPushButton()
        self.change_button.setObjectName("offerChangeDir")
        self.change_button.setAutoDefault(False)
        self.dir_error_label = PeerTextLabel(wrap=True, object_name="offerDirError")
        self.dir_error_label.setProperty(theme.TONE_PROPERTY, "warning")
        self.dir_error_label.setVisible(False)
        self.always_check = QCheckBox()
        self.always_check.setObjectName("offerAlways")
        self.always_check.setChecked(entry.always)

        self.reject_button = QPushButton()
        self.reject_button.setObjectName("offerReject")
        self.accept_button = QPushButton()
        self.accept_button.setObjectName("offerAccept")
        primary = self.accept_button.font()
        primary.setBold(True)  # nút chính; Enter vẫn là “Từ chối”
        self.accept_button.setFont(primary)
        self.accept_button.setProperty(theme.PRIMARY_PROPERTY, True)  # tô màu nhấn, không phải nút mặc định
        self.accept_button.setAutoDefault(False)
        self.reject_button.setAutoDefault(True)
        self.reject_button.setDefault(True)

        save_row = QHBoxLayout()
        save_row.setSpacing(theme.SPACING[1])
        save_row.addWidget(self.save_label, 1)
        save_row.addWidget(self.change_button, 0, Qt.AlignmentFlag.AlignVCenter)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.accept_button)
        layout = QVBoxLayout(box)
        layout.setSpacing(10)
        layout.addWidget(self.head_label)
        layout.addWidget(self.files_label)
        layout.addWidget(self.note_label)
        layout.addLayout(save_row)
        layout.addWidget(self.dir_error_label)
        layout.addWidget(self.always_check)
        layout.addSpacing(6)
        layout.addLayout(buttons)
        QWidget.setTabOrder(self.change_button, self.always_check)
        QWidget.setTabOrder(self.always_check, self.reject_button)
        QWidget.setTabOrder(self.reject_button, self.accept_button)
        self.retranslate()
        self.reject_button.setFocus()  # Tab tới “Nhận”; Enter / Space trên nút đang có focus

    def retranslate(self) -> None:
        owner = self._owner
        head, lines, _save = offer_parts(self.offer, owner.receive_dir)
        title = title_text()
        self.box.setWindowTitle(title)
        self.box.setAccessibleName(title)
        self.box.setAccessibleDescription(head)  # trình đọc màn hình đọc câu đầu khi hộp mở
        self.head_label.setText(head)
        self.files_label.setText("\n".join(lines))
        self.note_label.setText(disconnected_text(_peer_of(self.offer)))
        self.change_button.setText(change_text())
        self.change_button.setAccessibleName(change_name())
        self.always_check.setText(always_text())
        self.always_check.setAccessibleName(always_text())
        accept = accept_text()
        reject = reject_text()
        self.accept_button.setText(accept)
        self.accept_button.setAccessibleName(accept)
        self.reject_button.setText(reject)
        self.reject_button.setAccessibleName(reject)
        self.refresh()

    def refresh(self) -> None:
        """Áp trạng thái hiện tại (thư mục, đang đổi, lỗi, kết nối, ô tick) mà không dịch lại câu cố định."""
        owner = self._owner
        save = save_line(owner.receive_dir, owner.pending)
        self.save_label.setText(save or "")
        self.save_label.setVisible(save is not None)
        changing = owner.pending is not None
        self.change_button.setVisible(owner.receive_dir is not None)
        self.change_button.setEnabled(not changing)
        hint = pending_accept_hint() if changing else ""
        self.accept_button.setEnabled(not changing)
        self.accept_button.setToolTip(hint)
        self.accept_button.setAccessibleDescription(hint)
        error = "" if self.dir_error is None else texts.resolve(self.dir_error)
        self.dir_error_label.setText(error)
        self.dir_error_label.setVisible(bool(error))
        self.note_label.setVisible(not self.entry.connected)
        if self.always_check.isChecked() != self.entry.always:
            with QSignalBlocker(self.always_check):
                self.always_check.setChecked(self.entry.always)
        self.fit_height()

    def fit_height(self) -> None:
        """Hộp đang hiện: cao thêm khi chữ hay dòng hiện thêm cần nhiều chỗ hơn.

        Cửa sổ cấp cao có nhãn xuống dòng (heightForWidth) không tự cao lên khi nội dung đổi sau lúc
        `show()` (chiều cao tối thiểu của layout không tính heightForWidth), nên chữ bị cắt; ở đây
        tính `totalHeightForWidth` theo bề ngang hiện tại và chỉ nới, không thu (người dùng có thể đã
        kéo hộp to hơn)."""
        box = self.box
        layout = box.layout()
        if layout is None or not box.isVisible():
            return
        layout.activate()
        width = box.width()
        if layout.hasHeightForWidth():
            need = layout.totalHeightForWidth(width)
        else:
            need = layout.totalSizeHint().height()
        need = max(need, layout.totalMinimumSize().height())
        if need > box.height():
            box.resize(width, need)


class OfferPrompts(QObject):
    """Hộp hỏi nhận file đang mở (mỗi `TransferKey` một hộp) và hàng chờ hộp (xem docstring module)."""

    decided = Signal(object, bool)  # ý định: Nhận / Từ chối / Enter / Esc / nút X
    always_toggled = Signal(object, bool)
    change_dir_requested = Signal()
    opened = Signal(object)  # TransferKey: vừa mở một hộp

    def __init__(
        self, book: OfferBook, receive_dir: Path | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._book = book
        self._receive_dir = receive_dir
        self._pending: Path | None = None
        self._prompts: dict[TransferKey, _Prompt] = {}
        self._queue: list[TransferKey] = []
        book.changed.connect(self._on_changed)
        book.removed.connect(self._on_removed)

    # ---- Trạng thái chung --------------------------------------------------------------------

    @property
    def book(self) -> OfferBook:
        return self._book

    @property
    def receive_dir(self) -> Path | None:
        return self._receive_dir

    @property
    def pending(self) -> Path | None:
        """Thư mục nhận đang đổi sang (None: không đổi)."""
        return self._pending

    def set_receive_dir(self, receive_dir: Path | None) -> None:
        """Thư mục lưu ở dòng “Lưu vào” của các hộp mở sau lần gọi này và của các hộp đang mở."""
        self._receive_dir = receive_dir
        self._refresh_all()

    def set_receive_dir_pending(self, path: Path | None) -> None:
        """Đang đổi thư mục nhận sang `path` (None: xong): “Nhận” và “Đổi…” tắt trong lúc đổi. Một lần
        đổi mới bắt đầu (`path` khác None) thì gỡ lỗi đổi thư mục cũ ở các hộp đang mở."""
        self._pending = path
        if path is not None:
            for prompt in self._prompts.values():
                prompt.dir_error = None
        self._refresh_all()

    def set_dir_error(self, text: texts.Text | None) -> None:
        """Lỗi đổi thư mục nhận, chỉ hiện ở các hộp **đang mở** lúc gọi; hộp mở sau không mang theo
        (lỗi đi cùng hộp, mất khi hộp đóng). None → gỡ."""
        for prompt in self._prompts.values():
            prompt.dir_error = text or None
        self._refresh_all()

    # ---- Hộp -----------------------------------------------------------------------------------

    def show_prompt(self, key: TransferKey) -> bool:
        """Mở hộp cho `key` (hay xếp hàng khi đã có `PROMPTS_MAX_OPEN` hộp). False khi `key` không
        PENDING, đã có hộp hay đã xếp hàng."""
        entry = self._book.entry(key)
        if entry is None or entry.phase is not OfferPhase.PENDING:
            return False
        if key in self._prompts or key in self._queue:
            return False
        if len(self._prompts) >= PROMPTS_MAX_OPEN:
            self._queue.append(key)
            return True
        self._open(entry)
        return True

    def preview(self, key: TransferKey) -> QDialog | None:
        """Dựng hộp của lời mời `key` mà không hiện, không đăng ký, không nối nút (`--selftest`, ảnh
        chụp). Bên gọi giữ và xóa hộp; không có `key` → None."""
        entry = self._book.entry(key)
        return None if entry is None else _Prompt(entry, self).box

    def box(self, key: TransferKey) -> QDialog | None:
        """Hộp đang mở cho `key` (test, trợ năng)."""
        prompt = self._prompts.get(key)
        return None if prompt is None else prompt.box

    def keys(self) -> list[TransferKey]:
        """Key của các hộp đang mở, theo thứ tự mở."""
        return list(self._prompts)

    def queued(self) -> list[TransferKey]:
        """Key đang chờ tới lượt mở hộp, FIFO."""
        return list(self._queue)

    def close_all(self) -> None:
        """Đóng mọi hộp mà không quyết định và bỏ hàng chờ (host mới, app đang thoát)."""
        self._queue.clear()
        for key in list(self._prompts):
            self._dismiss(key, open_next=False)

    # ---- Bên trong -----------------------------------------------------------------------------

    def _refresh_all(self) -> None:
        for prompt in self._prompts.values():
            prompt.refresh()

    def _open(self, entry: OfferEntry) -> None:
        prompt = _Prompt(entry, self)
        key = entry.key
        self._prompts[key] = prompt
        prompt.accept_button.clicked.connect(lambda: self._clicked(prompt, True))
        prompt.reject_button.clicked.connect(lambda: self._clicked(prompt, False))
        prompt.change_button.clicked.connect(self.change_dir_requested)
        prompt.always_check.toggled.connect(lambda on: self.always_toggled.emit(key, bool(on)))
        prompt.box.finished.connect(lambda _result: self._finished(prompt))
        box: QWidget = prompt.box
        box.show()
        prompt.fit_height()  # `show()` không tính đủ heightForWidth của hàng “Lưu vào” + “Đổi…”
        box.raise_()
        box.activateWindow()
        self.opened.emit(key)

    def _open_next(self) -> None:
        while self._queue and len(self._prompts) < PROMPTS_MAX_OPEN:
            key = self._queue.pop(0)
            entry = self._book.entry(key)
            if entry is not None and entry.phase is OfferPhase.PENDING and key not in self._prompts:
                self._open(entry)

    def _clicked(self, prompt: _Prompt, accept: bool) -> None:
        if prompt.resolved:
            return
        prompt.resolved = True
        self.decided.emit(prompt.offer.key, accept)
        if not prompt.closed:  # book có thể đã đóng hộp khi nhận quyết định
            if accept:
                prompt.box.accept()
            else:
                prompt.box.reject()

    def _finished(self, prompt: _Prompt) -> None:
        prompt.closed = True
        key = prompt.offer.key
        if self._prompts.get(key) is prompt:
            del self._prompts[key]
        if not prompt.resolved:  # Esc hay nút X: từ chối
            prompt.resolved = True
            self.decided.emit(key, False)
        self._open_next()

    def _dismiss(self, key: TransferKey, *, open_next: bool = True) -> None:
        prompt = self._prompts.pop(key, None)
        if prompt is None:
            return
        prompt.resolved = True
        if not prompt.closed:
            prompt.closed = True
            prompt.box.close()
        if open_next:
            self._open_next()

    def _on_changed(self, key: TransferKey) -> None:
        entry = self._book.entry(key)
        if entry is None:
            return
        if entry.phase is not OfferPhase.PENDING:
            if key in self._queue:
                self._queue.remove(key)
            self._dismiss(key)
            return
        prompt = self._prompts.get(key)
        if prompt is not None:
            prompt.refresh()

    def _on_removed(self, key: TransferKey) -> None:
        if key in self._queue:
            self._queue.remove(key)
        self._dismiss(key)
