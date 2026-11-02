"""Màn lần chạy đầu (mvp F1, spec D1): `FirstRunForm`, `FirstRunChoice` và câu chữ của màn.

`home.StartPanel` dựng form này trong khối căn giữa (`startCard`); `main_window.MainWindow` hiện nó
ở trạng thái WELCOME (`show_welcome`) và ẩn ở STARTING / ERROR; `ui.app.GuiApp` đặt giá trị gợi ý và
nối các signal. Module này không import `home` hay `main_window`, không chạm node và không I/O: mọi
giá trị ban đầu (tên gợi ý, thư mục gợi ý, trạng thái tự khởi động) do `ui.app` đọc rồi truyền vào.
Chưa bấm “Bắt đầu” thì Teleport không chạy, không quảng bá (`ui.app`).

**Bố cục** (từ trên xuống, dưới logo + tên app của `StartPanel`): minh họa `illustration`
(`illustrations.Scene.WELCOME`, căn giữa, trang trí: không nhận Tab, không tên trợ năng); câu giá trị
`firstRunTagline` (SECTION); ba ý `firstRunFeatures` (icon 20 px tô `text_muted`, trang trí, cùng chữ thân):
`featureNoAccount`, `featureEncrypted`, `featureResume`; nhãn `firstRunNameLabel` (đậm vừa, buddy của
ô) + ô `firstRunNameEdit` + lỗi `firstRunNameError` (`tone=danger`, ẩn khi không lỗi) + câu mvp F1
`firstRunNameHint` (`tone=muted`, `texts.device_name_notice`); nhãn `firstRunDirCaption` + hàng
`firstRunDirLabel` (đường dẫn cắt giữa theo bề ngang, tooltip đầy đủ, chọn bằng chuột) và nút
`firstRunDirButton` “Đổi…” + lỗi `firstRunDirError`; hàng `firstRunAutostartRow` (nhãn
`firstRunAutostartLabel` + `widgets.ToggleSwitch` `firstRunAutostartSwitch`; ẩn khi hệ điều hành
không hỗ trợ) + giải thích `firstRunAutostartHint` (`tone=muted`) + câu trạng thái
`firstRunAutostartState` (`tone=warning`, chỉ khi registry ở OTHER/BLOCKED); câu đồng ý
`firstRunConsent` (`tone=muted`). Nút “Bắt đầu” là `StartPanel.start_button`, không nằm ở đây.
Khoảng cách 8 px trong một nhóm (cả từ minh họa tới câu giá trị), 16 px giữa các nhóm, 24 px sau
phần giới thiệu. Mọi nhãn là
`Qt.PlainText`; màu chỉ qua `theme.TONE_PROPERTY` (không thêm luật stylesheet), icon tô lại khi đổi
sáng/tối (`PaletteChange`).

**Ô tên** (spec D1 Q5): gợi ý do `ui.app.suggested_device_name` tính; gợi ý rỗng thì ô trống với
placeholder “Ví dụ: Laptop-Minh”. `setMaxLength(ui.settings.NAME_MAX_INPUT)`. Kiểm bằng
`core.messages.validate_device_name` trên `text().strip()` (cùng luật và cùng câu với Cài đặt:
`ui.settings.name_empty_text` / `name_invalid_text`): khi bấm “Bắt đầu”, khi Enter trong ô
(`submitted`) và khi rời ô (chỉ khi ô không rỗng và đã bị gõ sửa, không tính lúc cửa sổ mất kích hoạt
hay mở popup). Lỗi: nhãn ngay dưới ô, câu lỗi ghép vào đầu `accessibleDescription` của ô, sự kiện trợ
năng Alert (cố gắng tốt nhất); `validate` đặt tiêu điểm vào ô và chọn hết chữ. Gõ (`textEdited`) thì
ẩn lỗi. Chữ trùng gợi ý → `FirstRunChoice.name = None` (node dùng tên đã lưu hay hostname, không ghi
`name`); khác → đúng chữ đã strip.

**Thư mục nhận** (Q6): hiện thư mục gợi ý (`set_defaults`); “Đổi…” phát `change_dir_requested`
(`ui.app` mở `ReceiveDirController.choose_initial`), chọn xong `set_receive_dir` (ẩn lỗi thư mục).
`receive_dir_chosen` True khi thư mục đang hiện khác thư mục gợi ý. Lỗi thư mục (`set_dir_error`:
UNAVAILABLE khi node không mở được thư mục đã chọn, RESERVED khi chọn thư mục riêng của Teleport) hiện
ngay dưới hàng và ghép vào mô tả của nút “Đổi…”.

**Khởi động cùng Windows** (Q7): `set_defaults(autostart=None)` ẩn cả hàng (`FirstRunChoice.autostart
= None`); True/False là trạng thái ban đầu của công tắc. `autostart_hint` là câu trạng thái (chuỗi,
hay hàm trả chuỗi để dịch lại khi đổi ngôn ngữ; chuỗi đúng bằng câu `ui.settings.autostart_state_hint`
của OTHER/BLOCKED cũng được dịch lại); rỗng thì ẩn. Form không ghi registry.

**Trợ năng** (mvp N12): `firstRunForm` tên “Thiết lập {APP_NAME}”, mô tả = câu giá trị + ba ý. Nhãn
không nhận Tab (nội dung đã nằm trong mô tả của control); chuỗi Tab: ô tên → “Đổi…” → công tắc (khi
hiện) → “Bắt đầu” (nối ở `StartPanel`). `focus_target()`: có lỗi thư mục → “Đổi…”; còn lại ô tên
(có lỗi tên thì chọn hết chữ, không thì con trỏ cuối chữ, không chọn). Công tắc có chữ “Bật”/“Tắt”,
lỗi có chữ: không chỉ dùng màu. Tên/mô tả trợ năng của công tắc = nhãn / giải thích [+ câu trạng thái].

Chuỗi qua `QCoreApplication.translate("FirstRun", …)` gọi lúc dùng; câu dùng lại giữ ngữ cảnh gốc
(`Texts`, `Settings`, `ReceiveDir`, `Widgets`). Mọi `{path}` qua `send.printable`.
"""

from __future__ import annotations

import contextlib
import functools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QAccessible, QAccessibleEvent, QFocusEvent, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from teleport.app.autostart import AutostartState
from teleport.core.messages import validate_device_name
from teleport.ui import icons, texts, theme
from teleport.ui.illustrations import Illustration, Scene
from teleport.ui.send import printable
from teleport.ui.settings import (
    NAME_MAX_INPUT,
    autostart_state_hint,
    name_empty_text,
    name_invalid_text,
)
from teleport.ui.widgets import ToggleSwitch, safe_tooltip

_FEATURE_ICON = 20  # px
_FEATURES = (
    ("featureNoAccount", "cloud_off"),
    ("featureEncrypted", "lock_closed"),
    ("featureResume", "arrow_sync"),
)
_GROUP_GAP = theme.SPACING[3]  # 16 px giữa các nhóm
_ITEM_GAP = theme.SPACING[1]  # 8 px trong một nhóm
_INTRO_GAP = theme.SPACING[4]  # 24 px sau phần giới thiệu
_TIGHT_GAP = theme.SPACING[0]  # 4 px giữa ô và câu ngay dưới nó
_PALETTE_EVENTS = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)
# Rời ô vì cửa sổ mất kích hoạt hay mở popup: người dùng chưa rời ô thật, không kiểm.
_NO_CHECK_REASONS = (Qt.FocusReason.ActiveWindowFocusReason, Qt.FocusReason.PopupFocusReason)

TextSource = str | Callable[[], str]  # chữ cố định, hay hàm trả chữ đã dịch (dịch lại khi đổi ngôn ngữ)


# ---- Câu chữ -------------------------------------------------------------------------------------


def tagline_text() -> str:
    """Câu giá trị đầu màn."""
    return QCoreApplication.translate(
        "FirstRun", "Gửi file lớn giữa các máy trong cùng mạng. Không qua cloud."
    )


def feature_texts() -> tuple[str, str, str]:
    """Ba ý dưới câu giá trị (cùng thứ tự với `_FEATURES`)."""
    t = QCoreApplication.translate
    return (
        t("FirstRun", "Không tài khoản, không máy chủ trung gian"),
        t("FirstRun", "Mã hóa đầu cuối giữa hai máy"),
        t("FirstRun", "Tự nối lại khi rớt mạng, không phải gửi lại từ đầu"),
    )


def form_name_text() -> str:
    """Tên trợ năng của cả form."""
    return QCoreApplication.translate("FirstRun", "Thiết lập {app}").format(app=texts.APP_NAME)


def name_label_text() -> str:
    return QCoreApplication.translate("FirstRun", "Tên thiết bị")


def name_placeholder_text() -> str:
    """Placeholder của ô tên khi không có gợi ý."""
    return QCoreApplication.translate("FirstRun", "Ví dụ: Laptop-Minh")


def dir_caption_text() -> str:
    return QCoreApplication.translate("FirstRun", "Thư mục nhận file")


def change_dir_text() -> str:
    """Chữ trên nút đổi thư mục."""
    return QCoreApplication.translate("FirstRun", "Đổi…")


def change_dir_label() -> str:
    """Tên trợ năng và tooltip của nút đổi thư mục."""
    return QCoreApplication.translate("FirstRun", "Đổi thư mục nhận")


def dir_description_text(path: Path) -> str:
    """Mô tả trợ năng của nút đổi thư mục: thư mục đang chọn."""
    return texts.fill(
        QCoreApplication.translate("FirstRun", "Thư mục nhận: {path}"), path=printable(str(path))
    )


def autostart_label_text() -> str:
    return QCoreApplication.translate("FirstRun", "Khởi động cùng Windows")


def autostart_hint_text() -> str:
    return QCoreApplication.translate(
        "FirstRun",
        "Teleport chạy ẩn ở khay hệ thống từ khi bạn đăng nhập Windows, để luôn sẵn sàng nhận file.",
    )


def consent_text() -> str:
    """Câu đồng ý ngay trên nút “Bắt đầu” (cũng là mô tả trợ năng của nút)."""
    return QCoreApplication.translate(
        "FirstRun", "Bấm Bắt đầu để Teleport chạy và hiện máy này với các máy khác trong mạng."
    )


def autostart_failed_text() -> str:
    """Dải thông báo khi lần chạy đầu không bật được khởi động cùng Windows."""
    return QCoreApplication.translate(
        "FirstRun",
        "Chưa bật được khởi động cùng Windows vì Windows không cho ghi cài đặt khởi động. "
        "Bạn có thể bật lại trong Cài đặt.",
    )


def open_settings_text() -> str:
    """Nút của dải `autostart_failed_text`."""
    return QCoreApplication.translate("FirstRun", "Mở Cài đặt")


def _hint_source(hint: TextSource) -> TextSource:
    """Câu trạng thái truyền dạng chuỗi mà đúng là câu `autostart_state_hint` của một trạng thái → hàm
    dựng lại câu đó (dịch lại được khi đổi ngôn ngữ); chuỗi khác giữ nguyên."""
    if callable(hint) or not hint:
        return hint
    for state in (AutostartState.OTHER, AutostartState.BLOCKED):
        if hint == autostart_state_hint(state):
            return functools.partial(autostart_state_hint, state)
    return hint


def _resolve(source: TextSource | None) -> str:
    if source is None:
        return ""
    return source() if callable(source) else source


# ---- Kết quả -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FirstRunChoice:
    """Lựa chọn của người dùng ở màn lần chạy đầu (đã kiểm hợp lệ)."""

    name_text: str  # chữ trong ô (đã strip, hợp lệ): để hiện lại
    name: str | None  # cho `Node(name=…)`; None khi trùng gợi ý
    receive_dir: Path  # thư mục đang hiện
    receive_dir_chosen: bool  # đã chọn qua “Đổi…” và khác thư mục gợi ý
    autostart: bool | None  # None: hàng ẩn (không hỗ trợ)


# ---- Form ----------------------------------------------------------------------------------------


def _text_label(object_name: str, tone: str | None = None, *, wrap: bool = True) -> QLabel:
    """Nhãn chữ thuần, không nhận tiêu điểm, không chọn chữ."""
    label = QLabel()
    label.setObjectName(object_name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    if tone is not None:
        label.setProperty(theme.TONE_PROPERTY, tone)
    return label


def _medium(font: QFont) -> QFont:
    result = QFont(font)
    result.setWeight(QFont.Weight.DemiBold)  # font hệ thống thường không có Medium: DemiBold mới thấy
    return result


class FirstRunForm(QWidget):
    """Form của màn lần chạy đầu: tên thiết bị, thư mục nhận, khởi động cùng Windows (docstring module)."""

    submitted = Signal()  # Enter trong ô tên
    change_dir_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("firstRunForm")
        self._suggested = ""
        self._suggested_dir = Path()
        self._dir = Path()
        self._edited = False  # ô tên đã bị gõ sửa kể từ `set_defaults` / `restore`
        self._name_error: TextSource | None = None
        self._dir_error: TextSource | None = None
        self._autostart_supported = False
        self._autostart_hint: TextSource = ""

        self.illustration = Illustration(Scene.WELCOME, self)  # trang trí, không nhận Tab
        self.tagline_label = _text_label("firstRunTagline")
        self.tagline_label.setFont(theme.font_for(theme.TextStyle.SECTION, self.tagline_label.font()))
        self.features = QWidget(self)
        self.features.setObjectName("firstRunFeatures")
        self.features.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.feature_icons: list[QLabel] = []
        self.feature_labels: list[QLabel] = []
        features_layout = QVBoxLayout(self.features)
        features_layout.setContentsMargins(0, 0, 0, 0)
        features_layout.setSpacing(_ITEM_GAP)
        for object_name, _icon in _FEATURES:
            row = QWidget(self.features)
            row.setObjectName(object_name)
            icon = _text_label(f"{object_name}Icon", wrap=False)
            icon.setFixedSize(_FEATURE_ICON, _FEATURE_ICON)
            label = _text_label(f"{object_name}Text")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(_ITEM_GAP)
            row_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
            row_layout.addWidget(label, 1)
            features_layout.addWidget(row)
            self.feature_icons.append(icon)
            self.feature_labels.append(label)

        self.name_label = _text_label("firstRunNameLabel", wrap=False)
        self.name_label.setFont(_medium(self.name_label.font()))
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("firstRunNameEdit")
        self.name_edit.setMaxLength(NAME_MAX_INPUT)
        self.name_edit.installEventFilter(self)
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.name_edit.returnPressed.connect(self.submitted)
        self.name_label.setBuddy(self.name_edit)
        self.name_error_label = _text_label("firstRunNameError", "danger")
        self.name_error_label.setContentsMargins(0, _TIGHT_GAP, 0, 0)  # không dính sát mép dưới ô
        self.name_error_label.setVisible(False)
        self.name_hint_label = _text_label("firstRunNameHint", "muted")

        self.dir_caption = _text_label("firstRunDirCaption", wrap=False)
        self.dir_caption.setFont(_medium(self.dir_caption.font()))
        self.dir_label = QLabel(self)
        self.dir_label.setObjectName("firstRunDirLabel")
        self.dir_label.setTextFormat(Qt.TextFormat.PlainText)
        self.dir_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.dir_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.dir_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.dir_label.installEventFilter(self)  # cắt lại chữ mỗi khi nhãn đổi bề ngang
        self.dir_button = QPushButton(self)
        self.dir_button.setObjectName("firstRunDirButton")
        self.dir_button.setAutoDefault(False)
        self.dir_button.clicked.connect(self.change_dir_requested)
        self.dir_error_label = _text_label("firstRunDirError", "danger")
        self.dir_error_label.setContentsMargins(0, _TIGHT_GAP, 0, 0)
        self.dir_error_label.setVisible(False)

        self.autostart_row = QWidget(self)
        self.autostart_row.setObjectName("firstRunAutostartRow")
        self.autostart_label = _text_label("firstRunAutostartLabel")
        self.autostart_label.setFont(_medium(self.autostart_label.font()))
        self.autostart_switch = ToggleSwitch(self.autostart_row)
        self.autostart_switch.setObjectName("firstRunAutostartSwitch")
        self.autostart_hint_label = _text_label("firstRunAutostartHint", "muted")
        self.autostart_state_label = _text_label("firstRunAutostartState", "warning")
        self.autostart_state_label.setVisible(False)
        self.consent_label = _text_label("firstRunConsent", "muted")

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.illustration, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(_ITEM_GAP)  # minh họa đi cùng câu giá trị: khoảng cách trong nhóm
        column.addWidget(self.tagline_label)
        column.addSpacing(_ITEM_GAP)
        column.addWidget(self.features)
        column.addSpacing(_INTRO_GAP)

        column.addWidget(self.name_label)
        column.addSpacing(_ITEM_GAP)
        column.addWidget(self.name_edit)
        column.addWidget(self.name_error_label)
        column.addSpacing(_TIGHT_GAP)
        column.addWidget(self.name_hint_label)
        column.addSpacing(_GROUP_GAP)

        column.addWidget(self.dir_caption)
        column.addSpacing(_ITEM_GAP)
        dir_row = QHBoxLayout()
        dir_row.setContentsMargins(0, 0, 0, 0)
        dir_row.setSpacing(_ITEM_GAP)
        dir_row.addWidget(self.dir_label, 1)
        dir_row.addWidget(self.dir_button)
        column.addLayout(dir_row)
        column.addWidget(self.dir_error_label)

        # Hàng tự khởi động gồm cả giải thích và câu trạng thái: ẩn hàng là ẩn hết.
        autostart_column = QVBoxLayout(self.autostart_row)
        autostart_column.setContentsMargins(0, _GROUP_GAP, 0, 0)
        autostart_column.setSpacing(0)
        switch_row = QHBoxLayout()
        switch_row.setContentsMargins(0, 0, 0, 0)
        switch_row.setSpacing(_ITEM_GAP)
        switch_row.addWidget(self.autostart_label, 1)
        switch_row.addWidget(self.autostart_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        autostart_column.addLayout(switch_row)
        autostart_column.addSpacing(_TIGHT_GAP)
        autostart_column.addWidget(self.autostart_hint_label)
        autostart_column.addWidget(self.autostart_state_label)
        column.addWidget(self.autostart_row)
        column.addSpacing(_GROUP_GAP)
        column.addWidget(self.consent_label)

        QWidget.setTabOrder(self.name_edit, self.dir_button)
        QWidget.setTabOrder(self.dir_button, self.autostart_switch)
        self.autostart_row.setVisible(False)
        self._refresh_icons()
        self.retranslate()

    # ---- Giá trị -------------------------------------------------------------------------------

    @property
    def receive_dir(self) -> Path:
        """Thư mục nhận đang hiện."""
        return self._dir

    @property
    def suggested_name(self) -> str:
        return self._suggested

    @property
    def receive_dir_chosen(self) -> bool:
        """Thư mục đang hiện khác thư mục gợi ý (đã chọn qua “Đổi…”)."""
        return self._dir != self._suggested_dir

    @property
    def autostart_supported(self) -> bool:
        """Hàng tự khởi động có hiện (`set_defaults(autostart=…)` khác None)."""
        return self._autostart_supported

    def set_defaults(
        self,
        suggested_name: str,
        receive_dir: Path,
        autostart: bool | None,
        autostart_hint: TextSource = "",
    ) -> None:
        """Giá trị gợi ý: tên (rỗng → placeholder), thư mục, công tắc (None → ẩn hàng), câu trạng thái."""
        self._suggested = suggested_name.strip()
        self._suggested_dir = self._dir = Path(receive_dir)
        self.name_edit.setText(self._suggested)
        self._edited = False
        self._autostart_supported = autostart is not None
        self.autostart_switch.setChecked(bool(autostart))
        self._autostart_hint = _hint_source(autostart_hint)
        self.autostart_row.setVisible(self._autostart_supported)
        self._name_error = None
        self._dir_error = None
        self.retranslate()

    def restore(self, choice: FirstRunChoice) -> None:
        """Hiện lại lựa chọn trước (giữ tên gợi ý và thư mục gợi ý đã đặt bằng `set_defaults`)."""
        self.name_edit.setText(choice.name_text)
        self._edited = choice.name_text != self._suggested
        self._dir = Path(choice.receive_dir)
        if self._autostart_supported and choice.autostart is not None:
            self.autostart_switch.setChecked(choice.autostart)
        self._name_error = None
        self._dir_error = None
        self.retranslate()

    def set_receive_dir(self, path: Path) -> None:
        """Thư mục người dùng vừa chọn; ẩn lỗi thư mục."""
        self._dir = Path(path)
        self._dir_error = None
        self._update_dir()

    def set_name_error(self, text: TextSource | None) -> None:
        """Hiện (hay ẩn khi None/rỗng) câu lỗi ngay dưới ô tên."""
        before = self.name_error
        self._name_error = text or None
        # Câu lỗi không đổi (rời ô rồi bấm “Bắt đầu”) thì không đọc lại lần hai.
        self._update_name_error(alert=self._name_error is not None and self.name_error != before)

    def set_dir_error(self, text: TextSource | None) -> None:
        """Hiện (hay ẩn khi None/rỗng) câu lỗi ngay dưới hàng thư mục."""
        self._dir_error = text or None
        self._update_dir(alert=self._dir_error is not None)

    @property
    def name_error(self) -> str:
        """Câu lỗi tên đang hiện ("" khi không lỗi)."""
        return _resolve(self._name_error)

    @property
    def dir_error(self) -> str:
        """Câu lỗi thư mục đang hiện ("" khi không lỗi)."""
        return _resolve(self._dir_error)

    def validate(self) -> FirstRunChoice | None:
        """Kiểm ô tên; hợp lệ → `FirstRunChoice`, sai → hiện lỗi dưới ô, tiêu điểm vào ô, trả None."""
        text = self.name_edit.text().strip()
        error = self._name_problem(text)
        if error is not None:
            self.set_name_error(error)
            self.name_edit.setFocus(Qt.FocusReason.OtherFocusReason)
            self.name_edit.selectAll()
            return None
        if self._name_error is not None:
            self.set_name_error(None)
        return FirstRunChoice(
            name_text=text,
            name=None if text == self._suggested else text,
            receive_dir=self._dir,
            receive_dir_chosen=self.receive_dir_chosen,
            autostart=self.autostart_switch.isChecked() if self._autostart_supported else None,
        )

    def focus_target(self) -> QWidget:
        """Widget nhận tiêu điểm đầu ở WELCOME; chuẩn bị luôn vùng chọn của ô tên (docstring module)."""
        if self._dir_error is not None:
            return self.dir_button
        edit = self.name_edit
        if self._name_error is not None:
            edit.selectAll()
        else:
            edit.deselect()
            edit.end(False)
        return edit

    # ---- Chữ -----------------------------------------------------------------------------------

    def retranslate(self) -> None:
        """Đặt lại mọi chữ theo ngôn ngữ hiện tại; giữ chữ đang gõ và lỗi đang hiện (dịch lại câu lỗi)."""
        tagline = tagline_text()
        features = feature_texts()
        self.tagline_label.setText(tagline)
        for label, text in zip(self.feature_labels, features, strict=True):
            label.setText(text)
        self.setAccessibleName(form_name_text())
        self.setAccessibleDescription(" ".join([tagline, *(f"{text}." for text in features)]))
        name = name_label_text()
        self.name_label.setText(name)
        self.name_edit.setAccessibleName(name)
        self.name_edit.setPlaceholderText("" if self._suggested else name_placeholder_text())
        self.name_hint_label.setText(texts.device_name_notice())
        self.dir_caption.setText(dir_caption_text())
        self.dir_button.setText(change_dir_text())
        self.dir_button.setAccessibleName(change_dir_label())
        self.dir_button.setToolTip(safe_tooltip(change_dir_label()))
        autostart_label = autostart_label_text()
        self.autostart_label.setText(autostart_label)
        self.autostart_switch.setAccessibleName(autostart_label)
        self.autostart_switch.retranslate()
        self.autostart_hint_label.setText(autostart_hint_text())
        self.consent_label.setText(consent_text())
        self._update_autostart_state()
        self._update_name_error(alert=False)
        self._update_dir(alert=False)

    # ---- Bên trong -----------------------------------------------------------------------------

    @staticmethod
    def _name_problem(text: str) -> TextSource | None:
        """Câu lỗi của tên (hàm, để dịch lại khi đổi ngôn ngữ); hợp lệ → None."""
        if not text:
            return name_empty_text
        try:
            validate_device_name(text)
        except ValueError:
            return name_invalid_text
        return None

    def _on_name_edited(self, _text: str) -> None:
        self._edited = True
        if self._name_error is not None:
            self.set_name_error(None)

    def _check_on_leave(self) -> None:
        """Rời ô tên sau khi gõ sửa: kiểm ngay (ô rỗng thì chờ tới lúc bấm “Bắt đầu”)."""
        text = self.name_edit.text().strip()
        if not self._edited or not text:
            return
        error = self._name_problem(text)
        if error is not None:
            self.set_name_error(error)

    def _update_name_error(self, *, alert: bool) -> None:
        error = _resolve(self._name_error)
        self.name_error_label.setText(error)
        self.name_error_label.setVisible(bool(error))
        notice = texts.device_name_notice()
        self.name_edit.setAccessibleDescription(f"{error} {notice}" if error else notice)
        if alert and error:
            _alert(self.name_error_label)

    def _update_dir(self, *, alert: bool = False) -> None:
        shown = printable(str(self._dir))
        self.dir_label.setToolTip(safe_tooltip(shown) if shown else "")
        self.dir_label.setAccessibleName(dir_caption_text())
        self.dir_label.setAccessibleDescription(shown)
        self._elide()
        error = _resolve(self._dir_error)
        self.dir_error_label.setText(error)
        self.dir_error_label.setVisible(bool(error))
        description = dir_description_text(self._dir)
        self.dir_button.setAccessibleDescription(f"{description} {error}" if error else description)
        if alert and error:
            _alert(self.dir_error_label)

    def _update_autostart_state(self) -> None:
        state = _resolve(self._autostart_hint)
        self.autostart_state_label.setText(state)
        self.autostart_state_label.setVisible(bool(state))
        hint = autostart_hint_text()
        self.autostart_switch.setAccessibleDescription(f"{hint} {state}" if state else hint)

    def _elide(self) -> None:
        full = printable(str(self._dir))
        width = self.dir_label.contentsRect().width()
        text = full
        # Chưa hiện thì bề ngang nhãn chưa đúng: để nguyên chữ, sự kiện Resize sẽ cắt lại.
        if full and width > 0 and self.dir_label.isVisible():
            text = QFontMetrics(self.dir_label.font()).elidedText(full, Qt.TextElideMode.ElideMiddle, width)
        if self.dir_label.text() != text:
            self.dir_label.setText(text)

    def _refresh_icons(self) -> None:
        color = theme.tokens_for(self).text_muted
        for label, (_name, icon) in zip(self.feature_icons, _FEATURES, strict=True):
            label.setPixmap(icons.pixmap(icon, _FEATURE_ICON, color, label.devicePixelRatioF()))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if watched is self.dir_label and kind in (QEvent.Type.Resize, QEvent.Type.Show):
            self._elide()
        elif (
            watched is self.name_edit
            and kind == QEvent.Type.FocusOut
            and isinstance(event, QFocusEvent)
            and event.reason() not in _NO_CHECK_REASONS
        ):
            self._check_on_leave()
        return super().eventFilter(watched, event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in _PALETTE_EVENTS:
            self._refresh_icons()


def _alert(widget: QWidget) -> None:
    """Sự kiện trợ năng Alert (cố gắng tốt nhất: có HĐH không chuyển tới trình đọc màn hình)."""
    with contextlib.suppress(Exception):
        QAccessible.updateAccessibility(QAccessibleEvent(widget, QAccessible.Event.Alert))
