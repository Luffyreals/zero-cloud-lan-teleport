"""Form lần chạy đầu (mvp F1) trên `MainWindow` trần (spec D1 mục 3 Q5–Q7, mục 4, 5.1, 5.5; mục 14 thắng).

Viết từ spec, không từ code. Không node, không socket: cửa sổ dựng riêng, `show_welcome(...)` truyền
`autostart=` tường minh (spec 14.2). Test cần tiêu điểm/Tab dùng cửa sổ active (không
`WA_DontShowOnScreen`: trên nền `offscreen` cửa sổ đó không bao giờ active, xem `test_home_layout.py`).

Phần tử tìm theo objectName ở bảng mục 4. Câu chữ chép nguyên văn từ spec mục 4 / 5.1; câu F1 đọc từ
`docs/mvp.md` để tài liệu và giao diện không lệch nhau. Cuối file: hàm cấp module của `ui/app.py`
(`suggested_device_name`, `_mark_first_run_done`, spec 5.6, 14.12).
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QPoint, QRect, Qt, QTranslator
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QLineEdit, QWidget

# ---- Câu của spec D1 (mục 4, 5.1; câu lỗi tên của `ui.settings`) -----------------------------------
TAGLINE = "Gửi file lớn giữa các máy trong cùng mạng. Không qua cloud."
FEATURES = (
    "Không tài khoản, không máy chủ trung gian",
    "Mã hóa đầu cuối giữa hai máy",
    "Tự nối lại khi rớt mạng, không phải gửi lại từ đầu",
)
NAME_LABEL = "Tên thiết bị"
PLACEHOLDER = "Ví dụ: Laptop-Minh"
NAME_EMPTY = "Hãy nhập tên thiết bị."
NAME_INVALID = "Tên thiết bị cần từ 1 đến 64 ký tự và không có ký tự điều khiển."
DIR_CAPTION = "Thư mục nhận file"
CHANGE_DIR = "Đổi…"
CHANGE_DIR_LABEL = "Đổi thư mục nhận"
DIR_DESC = "Thư mục nhận: {path}"
AUTOSTART_LABEL = "Khởi động cùng Windows"
AUTOSTART_HINT = "Teleport chạy ẩn ở khay hệ thống từ khi bạn đăng nhập Windows, để luôn sẵn sàng nhận file."
CONSENT = "Bấm Bắt đầu để Teleport chạy và hiện máy này với các máy khác trong mạng."
FORM_NAME = "Thiết lập ZCL Teleport"
AUTOSTART_FAILED = (
    "Chưa bật được khởi động cùng Windows vì Windows không cho ghi cài đặt khởi động. "
    "Bạn có thể bật lại trong Cài đặt."
)
OPEN_SETTINGS = "Mở Cài đặt"
START = "Bắt đầu"
NAME_MAX_INPUT = 256  # `ui.settings.NAME_MAX_INPUT` (spec Q5 dùng lại hằng đó)

_MVP = Path(__file__).resolve().parents[2] / "docs" / "mvp.md"


def f1_notice() -> str:
    """Câu dưới ô tên thiết bị, nguyên văn mvp F1 (“Ngay dưới ô tên thiết bị có dòng: “…””)."""
    text = _MVP.read_text(encoding="utf-8")
    start = text.index("### F1.")
    f1 = text[start : text.index("\n### ", start + 1)]
    m = re.search(r"Ngay dưới ô tên thiết bị có dòng:\s*“([^”]+)”", f1)
    assert m, "mvp F1: không thấy dòng “Ngay dưới ô tên thiết bị có dòng: “…””"
    return m.group(1)


def shown(path: Path) -> str:
    from teleport.ui.send import printable

    return printable(str(path))


def shout(text: str) -> str:
    """Chữ in hoa, giữ nguyên chỗ giữ chỗ `{…}`."""
    return "".join(p if re.fullmatch(r"\{\w+\}", p) else p.upper() for p in re.split(r"(\{\w+\})", text))


class ShoutTranslator(QTranslator):
    """Translator giả trả chữ in hoa (như `test_home_layout.py`)."""

    def isEmpty(self):
        return False

    def translate(self, context, source_text, disambiguation=None, n=-1):
        return shout(source_text) if source_text else source_text


# =================================================================================================
# Fixture, hàm phụ trợ
# =================================================================================================


def settle() -> None:
    for _ in range(4):
        QApplication.processEvents()


@pytest.fixture
def window(qtbot):
    from teleport.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    return w


def show_window(window, qtbot, width: int = 980, height: int = 660, *, active: bool = False) -> None:
    if not active:
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.resize(width, height)
    window.show()
    qtbot.waitExposed(window)
    if active:
        window.activateWindow()
        window.raise_()
        qtbot.waitUntil(window.isActiveWindow, timeout=3000)
    settle()


def child(window, cls, name: str):
    found = window.findChild(cls, name)
    assert found is not None, f"không có {cls.__name__} objectName={name!r} (spec D1 mục 4)"
    return found


class Form(SimpleNamespace):
    """Các phần tử của form theo objectName (bảng mục 4)."""


def form(window) -> Form:
    from teleport.ui.widgets import ToggleSwitch

    return Form(
        root=child(window, QWidget, "firstRunForm"),
        tagline=child(window, QLabel, "firstRunTagline"),
        features=child(window, QWidget, "firstRunFeatures"),
        name_label=child(window, QLabel, "firstRunNameLabel"),
        edit=child(window, QLineEdit, "firstRunNameEdit"),
        name_error=child(window, QLabel, "firstRunNameError"),
        name_hint=child(window, QLabel, "firstRunNameHint"),
        dir_caption=child(window, QLabel, "firstRunDirCaption"),
        dir_label=child(window, QLabel, "firstRunDirLabel"),
        dir_button=child(window, QAbstractButton, "firstRunDirButton"),
        dir_error=child(window, QLabel, "firstRunDirError"),
        autostart_row=child(window, QWidget, "firstRunAutostartRow"),
        autostart_label=child(window, QLabel, "firstRunAutostartLabel"),
        switch=child(window, ToggleSwitch, "firstRunAutostartSwitch"),
        autostart_hint=child(window, QLabel, "firstRunAutostartHint"),
        autostart_state=child(window, QLabel, "firstRunAutostartState"),
        consent=child(window, QLabel, "firstRunConsent"),
        start=child(window, QAbstractButton, "startButton"),
    )


def emitted(window) -> list:
    got: list = []
    window.start_requested.connect(got.append)
    return got


def visible(widget, window) -> bool:
    return widget.isVisibleTo(window)


def send_text(widget, text: str) -> None:
    """Gõ từng ký tự bằng `QKeyEvent` mang chữ (phát `textEdited` như bàn phím thật).

    Không dùng `QTest.keyClicks`: với ký tự ngoài ASCII (“à”, “Đ”) PySide6 6.12 làm tiến trình chết
    (0xC0000409), đã thử.
    """
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    for ch in text:
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(
                widget, QKeyEvent(kind, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier, ch)
            )


def type_into(edit: QLineEdit, text: str) -> None:
    """Gõ như người dùng (phát `textEdited`): xóa chữ cũ bằng bàn phím rồi gõ `text`."""
    edit.setFocus()
    edit.selectAll()
    QTest.keyClick(edit, Qt.Key.Key_Backspace)
    if text:
        send_text(edit, text)


def top_in(widget: QWidget, ancestor: QWidget) -> int:
    return widget.mapTo(ancestor, QPoint(0, 0)).y()


def in_viewport(widget: QWidget, scroll) -> bool:
    viewport = scroll.viewport()
    top_left = widget.mapTo(viewport, QPoint(0, 0))
    return viewport.rect().contains(QRect(top_left, widget.size()))


def focus() -> QWidget | None:
    return QApplication.focusWidget()


def choice_of(window):
    """`first_run.validate()` không lỗi (form hợp lệ) → FirstRunChoice."""
    c = window.first_run.validate()
    assert c is not None, "form hợp lệ mà validate() trả None"
    return c


# =================================================================================================
# Câu chữ, ô tên
# =================================================================================================


def test_first_run_texts_match_spec():
    from teleport.ui import first_run

    assert first_run.tagline_text() == TAGLINE
    assert tuple(first_run.feature_texts()) == FEATURES
    assert first_run.name_label_text() == NAME_LABEL
    assert first_run.name_placeholder_text() == PLACEHOLDER
    assert first_run.dir_caption_text() == DIR_CAPTION
    assert first_run.change_dir_text() == CHANGE_DIR
    assert first_run.change_dir_label() == CHANGE_DIR_LABEL
    assert first_run.autostart_label_text() == AUTOSTART_LABEL
    assert first_run.autostart_hint_text() == AUTOSTART_HINT
    assert first_run.consent_text() == CONSENT
    assert first_run.autostart_failed_text() == AUTOSTART_FAILED
    assert first_run.open_settings_text() == OPEN_SETTINGS


def test_first_run_choice_is_frozen_with_spec_fields(tmp_path):
    from teleport.ui.first_run import FirstRunChoice

    c = FirstRunChoice(
        name_text="PC Nhà", name="PC Nhà", receive_dir=tmp_path, receive_dir_chosen=True, autostart=None
    )
    assert [f.name for f in dataclasses.fields(c)] == [
        "name_text",
        "name",
        "receive_dir",
        "receive_dir_chosen",
        "autostart",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.name = "khac"  # type: ignore[misc]


def test_welcome_prefills_suggested_name_and_f1_notice(window, qtbot):
    from teleport.ui import texts
    from teleport.ui.main_window import ViewState

    window.show_welcome("Laptop-Minh")
    show_window(window, qtbot)
    f = form(window)
    assert window.view_state is ViewState.WELCOME
    assert window.first_run is f.root, "MainWindow.first_run là form của StartPanel (spec 5.5)"
    assert f.edit.text() == "Laptop-Minh"
    assert f.name_hint.text() == f1_notice(), "câu F1 nguyên văn mvp"
    assert f.name_hint.text() == texts.device_name_notice()
    assert visible(f.name_hint, window)
    assert f.name_hint.textFormat() == Qt.TextFormat.PlainText
    assert top_in(f.name_hint, window) > top_in(f.edit, window), "câu F1 nằm dưới ô tên"
    assert not visible(f.name_error, window), "chưa có lỗi thì nhãn lỗi ẩn"
    assert f.edit.maxLength() == NAME_MAX_INPUT
    assert f.tagline.text() == TAGLINE
    assert f.name_label.text() == NAME_LABEL
    assert f.name_label.buddy() is f.edit, "nhãn ô tên là buddy của ô"
    assert f.dir_caption.text() == DIR_CAPTION
    assert f.consent.text() == CONSENT
    assert plain_text(f.dir_button) == CHANGE_DIR
    assert plain_text(f.start) == START
    feature_texts = [lbl.text() for lbl in f.features.findChildren(QLabel) if lbl.text()]
    assert feature_texts == list(FEATURES), feature_texts
    for name in ("featureNoAccount", "featureEncrypted", "featureResume"):
        assert f.features.findChild(QWidget, name) is not None, f"thiếu ý {name}"


def plain_text(button) -> str:
    return button.text().replace("&&", "\0").replace("&", "").replace("\0", "&")


def test_welcome_empty_suggestion_shows_placeholder_and_requires_name(window, qtbot):
    window.show_welcome("")
    show_window(window, qtbot)
    f = form(window)
    got = emitted(window)
    assert f.edit.text() == ""
    assert f.edit.placeholderText() == PLACEHOLDER
    assert "Teleport-" not in f.edit.text()
    f.start.click()
    assert got == [], "tên rỗng: không phát start_requested"
    assert visible(f.name_error, window)
    assert f.name_error.text() == NAME_EMPTY
    # Chỉ khoảng trắng cũng là rỗng (kiểm `text().strip()`).
    type_into(f.edit, "   ")
    f.start.click()
    assert got == []
    assert f.name_error.text() == NAME_EMPTY


def test_untouched_name_gives_none(window, qtbot):
    from teleport.ui.first_run import FirstRunChoice

    window.show_welcome("Laptop-Minh", autostart=None)
    show_window(window, qtbot)
    got = emitted(window)
    form(window).start.click()
    [c] = got
    assert isinstance(c, FirstRunChoice)
    assert c.name is None, "chữ trùng gợi ý: node dùng tên đã lưu/hostname, không ghi name"
    assert c.name_text == "Laptop-Minh"
    assert c.receive_dir_chosen is False


def test_edited_name_is_stripped_and_passed(window, qtbot):
    window.show_welcome("Laptop-Minh", autostart=None)
    show_window(window, qtbot)
    f = form(window)
    got = emitted(window)
    type_into(f.edit, "  PC Nhà  ")
    f.start.click()
    [c] = got
    assert c.name == "PC Nhà"
    assert c.name_text == "PC Nhà"


def test_edited_name_equal_to_suggestion_after_strip_gives_none(window, qtbot):
    """Q5: so chữ **đã strip** với gợi ý; gõ lại đúng gợi ý kèm khoảng trắng vẫn là “không đổi”."""
    window.show_welcome("Laptop-Minh", autostart=None)
    show_window(window, qtbot)
    f = form(window)
    got = emitted(window)
    type_into(f.edit, " Laptop-Minh ")
    f.start.click()
    [c] = got
    assert c.name is None
    assert c.name_text == "Laptop-Minh"


def test_invalid_name_shows_error_below_field(window, qtbot):
    window.show_welcome("Laptop-Minh", autostart=None)
    show_window(window, qtbot, active=True)
    f = form(window)
    got = emitted(window)

    too_long = "x" * 65
    type_into(f.edit, too_long)
    f.start.click()
    assert got == [], "tên 65 ký tự: không phát"
    assert visible(f.name_error, window)
    assert f.name_error.text() == NAME_INVALID
    assert f.name_error.textFormat() == Qt.TextFormat.PlainText
    edit_bottom = top_in(f.edit, window) + f.edit.height()
    assert edit_bottom <= top_in(f.name_error, window) < top_in(f.name_hint, window), (
        "lỗi nằm ngay dưới ô tên, trên câu F1"
    )
    qtbot.waitUntil(lambda: focus() is f.edit, timeout=3000)
    assert f.edit.selectedText() == too_long, "có lỗi: chọn hết chữ trong ô"
    desc = f.edit.accessibleDescription()
    assert desc.startswith(NAME_INVALID), f"câu lỗi ghép vào đầu mô tả trợ năng: {desc!r}"
    assert f1_notice() in desc

    # Ký tự điều khiển (đặt bằng code: bàn phím không gõ được \x07).
    f.edit.setText("May\x07A")
    f.start.click()
    assert got == []
    assert visible(f.name_error, window)
    assert f.name_error.text() == NAME_INVALID


def test_name_with_exactly_64_chars_is_accepted(window, qtbot):
    window.show_welcome("Laptop-Minh", autostart=None)
    show_window(window, qtbot)
    f = form(window)
    got = emitted(window)
    type_into(f.edit, "y" * 64)
    f.start.click()
    [c] = got
    assert c.name == "y" * 64
    assert not visible(f.name_error, window)


def test_name_error_hides_when_editing(window, qtbot):
    window.show_welcome("", autostart=None)
    show_window(window, qtbot)
    f = form(window)
    f.start.click()
    assert visible(f.name_error, window)
    send_text(f.edit, "a")
    assert not visible(f.name_error, window), "gõ vào ô (textEdited) thì ẩn lỗi"
    assert NAME_EMPTY not in f.edit.accessibleDescription()
    assert f1_notice() in f.edit.accessibleDescription()


def test_name_checked_on_focus_out_only_when_edited_and_not_empty(window, qtbot):
    """Spec 14.7: rời ô thì kiểm, chỉ khi ô đã bị sửa và không rỗng; lỗi “rỗng” chỉ khi bấm Bắt đầu/Enter."""
    window.show_welcome("Laptop-Minh", autostart=True)
    show_window(window, qtbot, active=True)
    f = form(window)

    # Sửa thành rỗng rồi rời ô: không hiện lỗi “rỗng”.
    type_into(f.edit, "")
    f.dir_button.setFocus()
    qtbot.waitUntil(lambda: focus() is f.dir_button, timeout=3000)
    settle()
    assert not visible(f.name_error, window), "rỗng + rời ô: chưa báo"

    # Sửa thành tên sai rồi rời ô: báo ngay.
    type_into(f.edit, "z" * 65)
    f.dir_button.setFocus()
    qtbot.waitUntil(lambda: focus() is f.dir_button, timeout=3000)
    qtbot.waitUntil(lambda: visible(f.name_error, window), timeout=3000)
    assert f.name_error.text() == NAME_INVALID


def test_focus_out_without_edit_does_not_validate(window, qtbot):
    """Ô chưa bị sửa (gợi ý rỗng hiếm gặp): rời ô không hiện lỗi."""
    window.show_welcome("", autostart=True)
    show_window(window, qtbot, active=True)
    f = form(window)
    f.edit.setFocus()
    qtbot.waitUntil(lambda: focus() is f.edit, timeout=3000)
    f.dir_button.setFocus()
    qtbot.waitUntil(lambda: focus() is f.dir_button, timeout=3000)
    settle()
    assert not visible(f.name_error, window)


def test_enter_in_name_field_submits_once(window, qtbot):
    from teleport.ui.first_run import FirstRunChoice

    window.show_welcome("Laptop-Minh", autostart=True)
    show_window(window, qtbot, active=True)
    f = form(window)
    got = emitted(window)
    f.edit.setFocus()
    QTest.keyClick(f.edit, Qt.Key.Key_Return)
    settle()
    assert len(got) == 1, f"Enter phải phát start_requested đúng một lần, được {len(got)}"
    assert isinstance(got[0], FirstRunChoice)
    assert got[0].autostart is True


def test_enter_with_invalid_name_shows_error_and_does_not_submit(window, qtbot):
    window.show_welcome("", autostart=None)
    show_window(window, qtbot, active=True)
    f = form(window)
    got = emitted(window)
    f.edit.setFocus()
    QTest.keyClick(f.edit, Qt.Key.Key_Enter)
    settle()
    assert got == []
    assert visible(f.name_error, window)
    assert f.name_error.text() == NAME_EMPTY


# =================================================================================================
# Hàng thư mục nhận
# =================================================================================================


def test_welcome_default_receive_dir_is_paths_default(window, fake_default_receive_dir):
    window.show_welcome("Laptop-Minh")
    assert window.first_run.receive_dir == fake_default_receive_dir
    assert not fake_default_receive_dir.exists(), "chỉ hiện, không tạo thư mục (Q6)"


def test_dir_row_shows_path_and_change_emits(window, qtbot, tmp_path):
    path = tmp_path / "Nhận File" / "rất dài" / ("thư-mục-" * 12)
    window.show_welcome("Laptop-Minh", path, autostart=None)
    show_window(window, qtbot)
    f = form(window)
    assert f.dir_caption.text() == DIR_CAPTION
    from teleport.ui.widgets import safe_tooltip

    assert f.dir_label.toolTip() in (safe_tooltip(shown(path)), safe_tooltip(str(path))), (
        "tooltip đầy đủ qua widgets.safe_tooltip"
    )
    assert f.dir_label.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert f.dir_label.textFormat() == Qt.TextFormat.PlainText
    assert f.dir_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    assert plain_text(f.dir_button) == CHANGE_DIR
    assert f.dir_button.toolTip() in (CHANGE_DIR_LABEL, safe_tooltip(CHANGE_DIR_LABEL))
    clicks: list = []
    window.change_first_run_dir_requested.connect(lambda: clicks.append(1))
    assert not path.exists(), "không I/O khi hiện thư mục"
    f.dir_button.click()
    assert clicks == [1]


def test_dir_label_elides_long_path_in_the_middle(window, qtbot, tmp_path):
    """14.10: đường dẫn dài cắt giữa theo bề ngang (không làm khối rộng ra)."""
    path = tmp_path / ("a" * 120) / "cuoi-cung"
    window.show_welcome("Laptop-Minh", path, autostart=None)
    show_window(window, qtbot)
    f = form(window)
    text = f.dir_label.text()
    assert text != str(path) and "…" in text, f"đường dẫn dài phải được cắt: {text!r}"
    assert text.endswith("cuoi-cung"), "cắt giữa: giữ phần cuối"
    assert f.dir_label.width() <= f.root.width()


def test_set_receive_dir_marks_chosen_only_when_different(window, qtbot, tmp_path):
    suggested = tmp_path / "goi-y"
    other = tmp_path / "khac"
    window.show_welcome("Laptop-Minh", suggested, autostart=None)
    show_window(window, qtbot)
    f = form(window)
    c = choice_of(window)
    assert c.receive_dir == suggested and c.receive_dir_chosen is False

    window.first_run.set_receive_dir(suggested)
    c = choice_of(window)
    assert c.receive_dir == suggested and c.receive_dir_chosen is False, "chọn lại đúng thư mục gợi ý"

    window.first_run.set_receive_dir(other)
    assert window.first_run.receive_dir == other
    c = choice_of(window)
    assert c.receive_dir == other and c.receive_dir_chosen is True
    assert shown(other) in f.dir_label.toolTip() or shown(other) in f.dir_label.text()
    assert shown(other) in f.dir_button.accessibleDescription()

    window.first_run.set_receive_dir(suggested)
    assert choice_of(window).receive_dir_chosen is False


def test_dir_error_shown_and_cleared_by_new_dir(window, qtbot, tmp_path):
    from teleport.ui.receive_dir import ChangeError, change_error_text

    suggested = tmp_path / "goi-y"
    bad = tmp_path / "hong"
    window.show_welcome("Laptop-Minh", suggested, autostart=None)
    show_window(window, qtbot)
    f = form(window)
    assert not visible(f.dir_error, window)
    text = change_error_text(ChangeError.UNAVAILABLE, bad)
    window.first_run.set_dir_error(text)
    assert visible(f.dir_error, window)
    assert f.dir_error.text() == text
    assert top_in(f.dir_error, window) >= top_in(f.dir_button, window) + f.dir_button.height(), (
        "lỗi thư mục nằm dưới hàng thư mục"
    )
    assert text in f.dir_button.accessibleDescription(), "câu lỗi nằm trong mô tả trợ năng của [Đổi…]"

    window.first_run.set_receive_dir(tmp_path / "tot")
    assert not visible(f.dir_error, window), "chọn thư mục mới thì ẩn lỗi"
    assert text not in f.dir_button.accessibleDescription()

    window.first_run.set_dir_error(text)
    window.first_run.set_dir_error(None)
    assert not visible(f.dir_error, window)


def test_show_welcome_dir_error_argument_shows_error(window, qtbot, tmp_path):
    from teleport.ui.receive_dir import ChangeError, change_error_text

    text = change_error_text(ChangeError.RESERVED, tmp_path / ".teleport")
    window.show_welcome("Laptop-Minh", tmp_path / "goi-y", autostart=None, dir_error=text)
    show_window(window, qtbot)
    f = form(window)
    assert visible(f.dir_error, window)
    assert f.dir_error.text() == text


# =================================================================================================
# Hàng khởi động cùng Windows
# =================================================================================================


def test_autostart_row_hidden_when_unsupported(window, qtbot, tmp_path):
    window.show_welcome("Laptop-Minh", tmp_path / "d", autostart=None)
    show_window(window, qtbot)
    f = form(window)
    assert not visible(f.autostart_row, window)
    assert not visible(f.switch, window)
    assert choice_of(window).autostart is None

    # Gọi kiểu cũ (không có `autostart`): cũng ẩn.
    window.show_welcome("Laptop-Minh")
    assert not visible(f.autostart_row, window)
    assert choice_of(window).autostart is None


def test_autostart_switch_default_and_hint(window, qtbot, tmp_path):
    from teleport.app.autostart import AutostartState
    from teleport.ui.settings import autostart_state_hint

    window.show_welcome("Laptop-Minh", tmp_path / "d", autostart=True)
    show_window(window, qtbot)
    f = form(window)
    assert visible(f.autostart_row, window)
    assert f.autostart_label.text() == AUTOSTART_LABEL
    assert f.autostart_hint.text() == AUTOSTART_HINT
    assert f.switch.isChecked()
    assert not visible(f.autostart_state, window), "không có câu trạng thái khi không có hint"
    assert choice_of(window).autostart is True
    f.switch.click()
    assert not f.switch.isChecked()
    assert choice_of(window).autostart is False

    hint = autostart_state_hint(AutostartState.OTHER)
    window.show_welcome("Laptop-Minh", tmp_path / "d", autostart=False, autostart_hint=hint)
    assert not f.switch.isChecked()
    assert visible(f.autostart_state, window)
    assert f.autostart_state.text() == hint
    assert hint in f.switch.accessibleDescription()
    assert choice_of(window).autostart is False


def test_autostart_switch_toggles_with_space(window, qtbot, tmp_path):
    window.show_welcome("Laptop-Minh", tmp_path / "d", autostart=True)
    show_window(window, qtbot, active=True)
    f = form(window)
    f.switch.setFocus()
    qtbot.waitUntil(lambda: focus() is f.switch, timeout=3000)
    QTest.keyClick(f.switch, Qt.Key.Key_Space)
    assert not f.switch.isChecked()
    assert choice_of(window).autostart is False


# =================================================================================================
# Trạng thái, tiêu điểm, trợ năng, cỡ cửa sổ
# =================================================================================================


def test_welcome_hides_status_and_retry_starting_and_error_hide_form(window, qtbot, tmp_path):
    window.show_welcome("Laptop-Minh", tmp_path / "d", autostart=True)
    show_window(window, qtbot)
    w = window
    f = form(w)
    for name in ("status_icon", "status_label", "detail_label", "hint_label", "starting_bar", "retry_button"):
        assert not visible(getattr(w, name), w), f"WELCOME phải ẩn {name}"
    assert visible(w.first_run, w) and visible(f.start, w)

    w.show_starting()
    settle()
    assert not visible(w.first_run, w), "STARTING ẩn form"
    assert not visible(f.start, w)
    assert visible(w.starting_bar, w) and visible(w.status_label, w)

    w.show_error("port", "Address already in use")
    settle()
    assert not visible(w.first_run, w), "ERROR ẩn form"
    assert not visible(f.start, w)
    assert visible(w.retry_button, w) and visible(w.status_label, w)

    w.show_welcome("Laptop-Minh", tmp_path / "d", autostart=True)
    settle()
    assert visible(w.first_run, w)
    assert not visible(w.retry_button, w) and not visible(w.status_label, w)


def test_welcome_initial_focus_and_tab_order(window, qtbot, tmp_path):
    from teleport.ui.receive_dir import ChangeError, change_error_text

    show_window(window, qtbot, active=True)
    window.show_welcome("Laptop-Minh", tmp_path / "d", autostart=True)
    f = form(window)
    qtbot.waitUntil(lambda: focus() is f.edit, timeout=3000)
    assert f.edit.cursorPosition() == len("Laptop-Minh"), "con trỏ cuối chữ"
    assert f.edit.selectedText() == "", "tiêu điểm đầu: không chọn hết"
    assert window.first_run.focus_target() is f.edit

    order = [f.edit]
    for _ in range(3):
        QTest.keyClick(focus(), Qt.Key.Key_Tab)
        settle()
        order.append(focus())
    assert order == [f.edit, f.dir_button, f.switch, f.start], [x.objectName() for x in order if x]

    # Hàng tự khởi động ẩn: bỏ công tắc khỏi chuỗi Tab.
    window.show_welcome("Laptop-Minh", tmp_path / "d", autostart=None)
    qtbot.waitUntil(lambda: focus() is f.edit, timeout=3000)
    QTest.keyClick(focus(), Qt.Key.Key_Tab)
    settle()
    assert focus() is f.dir_button
    QTest.keyClick(focus(), Qt.Key.Key_Tab)
    settle()
    assert focus() is f.start

    # Có lỗi thư mục: tiêu điểm ở [Đổi…].
    window.show_welcome(
        "Laptop-Minh",
        tmp_path / "d",
        autostart=True,
        dir_error=change_error_text(ChangeError.UNAVAILABLE, tmp_path / "x"),
    )
    qtbot.waitUntil(lambda: focus() is f.dir_button, timeout=3000)
    assert window.first_run.focus_target() is f.dir_button


def test_labels_do_not_take_focus(window, qtbot, tmp_path):
    window.show_welcome("Laptop-Minh", tmp_path / "d", autostart=True)
    f = form(window)
    for label in (f.tagline, f.name_hint, f.dir_label):
        assert label.focusPolicy() == Qt.FocusPolicy.NoFocus, label.objectName()


def test_welcome_illustration_above_tagline_and_centered(window, qtbot, tmp_path):
    """Spec G6 mục 3: `FirstRunForm.illustration` (cảnh WELCOME) căn giữa, ngay trên câu giá trị,
    khoảng cách theo `theme.SPACING`, rộng ≤ 240 (mục 7)."""
    from teleport.ui import theme
    from teleport.ui.illustrations import Illustration, Scene

    show_window(window, qtbot)
    window.show_welcome("Laptop-Minh", tmp_path / "d", autostart=True)
    settle()
    f = form(window)
    ill = window.first_run.illustration
    assert isinstance(ill, Illustration)
    assert ill.scene is Scene.WELCOME
    assert visible(ill, window)
    assert ill.width() <= 240
    root = f.root
    gap = top_in(f.tagline, root) - (top_in(ill, root) + ill.height())
    assert gap in theme.SPACING, f"khoảng cách tới câu giá trị {gap} px không thuộc theme.SPACING"
    center = ill.mapTo(root, QPoint(0, 0)).x() + ill.width() / 2
    assert abs(center - root.width() / 2) <= 2, f"minh họa lệch ngang: tâm {center}, form rộng {root.width()}"


def test_welcome_illustration_is_decorative_and_not_in_tab_chain(window, qtbot, tmp_path):
    show_window(window, qtbot, active=True)
    window.show_welcome("Laptop-Minh", tmp_path / "d", autostart=True)
    f = form(window)
    qtbot.waitUntil(lambda: focus() is f.edit, timeout=3000)
    ill = window.first_run.illustration
    assert ill.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert ill.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert ill.accessibleName() == "" and ill.accessibleDescription() == ""
    seen = []
    for key in (Qt.Key.Key_Tab,) * 6 + (Qt.Key.Key_Backtab,) * 6:
        QTest.keyClick(focus(), key)
        settle()
        seen.append(focus())
    assert ill not in seen
    assert f.start in seen, "đối chứng: Tab vẫn tới “Bắt đầu”"


def test_accessible_names_and_descriptions(window, qtbot, tmp_path):
    from teleport.app.autostart import AutostartState
    from teleport.ui.settings import autostart_state_hint

    path = tmp_path / "Nhận"
    window.show_welcome("Laptop-Minh", path, autostart=True)
    f = form(window)
    assert f.root.accessibleName() == FORM_NAME
    root_desc = f.root.accessibleDescription()
    for part in (TAGLINE, *FEATURES):
        assert part in root_desc, f"mô tả của form thiếu {part!r}: {root_desc!r}"

    assert f.edit.accessibleName() == NAME_LABEL
    assert f.edit.accessibleDescription() == f1_notice(), "không lỗi: mô tả = câu F1"

    assert f.dir_button.accessibleName() == CHANGE_DIR_LABEL
    assert DIR_DESC.format(path=shown(path)) in f.dir_button.accessibleDescription()

    assert f.switch.accessibleName() == AUTOSTART_LABEL
    assert AUTOSTART_HINT in f.switch.accessibleDescription()

    assert f.start.accessibleDescription() == CONSENT

    hint = autostart_state_hint(AutostartState.BLOCKED)
    window.show_welcome("Laptop-Minh", path, autostart=False, autostart_hint=hint)
    desc = f.switch.accessibleDescription()
    assert AUTOSTART_HINT in desc and hint in desc


def test_welcome_at_min_size_scrolls_without_horizontal_bar(window, qtbot, tmp_path):
    show_window(window, qtbot, 720, 460, active=True)
    window.show_welcome("Laptop-Minh", tmp_path / "Nhan", autostart=True)
    settle()
    f = form(window)
    scroll = window.start_view.start_scroll
    qtbot.waitUntil(lambda: focus() is f.edit, timeout=3000)
    settle()
    hbar = scroll.horizontalScrollBar()
    assert not hbar.isVisible() or hbar.maximum() == 0, "720x460: không cuộn ngang"
    assert in_viewport(f.edit, scroll), "lúc mở: ô tên nằm trong vùng thấy"
    assert in_viewport(window.title_label, scroll), "lúc mở: đầu khối nằm trong vùng thấy"

    # Tab tới “Bắt đầu”: vùng cuộn tự cuộn tới nút.
    for _ in range(6):
        if focus() is f.start:
            break
        QTest.keyClick(focus(), Qt.Key.Key_Tab)
        settle()
    assert focus() is f.start, "tới được “Bắt đầu” bằng Tab ở 720x460"
    qtbot.waitUntil(lambda: in_viewport(f.start, scroll), timeout=3000)

    # Đặt tiêu điểm bằng code (về ô tên rồi lại “Bắt đầu”) cũng cuộn tới.
    f.edit.setFocus()
    qtbot.waitUntil(lambda: in_viewport(f.edit, scroll), timeout=3000)
    f.start.setFocus()
    qtbot.waitUntil(lambda: in_viewport(f.start, scroll), timeout=3000)
    assert not hbar.isVisible() or hbar.maximum() == 0


def test_retranslate_keeps_typed_name_and_error(window, qtbot, tmp_path):
    from teleport.app.autostart import AutostartState
    from teleport.ui.settings import autostart_state_hint

    hint = autostart_state_hint(AutostartState.OTHER)
    window.show_welcome("Laptop-Minh", tmp_path / "d", autostart=False, autostart_hint=hint)
    show_window(window, qtbot)
    f = form(window)
    type_into(f.edit, "w" * 65)
    f.start.click()
    assert f.name_error.text() == NAME_INVALID
    off_text = f.switch.state_text()

    translator = ShoutTranslator()
    QCoreApplication.installTranslator(translator)
    try:
        qtbot.waitUntil(lambda: f.tagline.text() == shout(TAGLINE), timeout=3000)
        assert f.edit.text() == "w" * 65, "dịch lại không xóa chữ đang gõ"
        assert visible(f.name_error, window), "dịch lại giữ lỗi đang hiện"
        assert f.name_error.text() == shout(NAME_INVALID), "câu lỗi được dịch lại"
        assert f.name_hint.text() == shout(f1_notice())
        assert f.autostart_hint.text() == shout(AUTOSTART_HINT)
        assert f.switch.state_text() == shout(off_text), "14.14: ToggleSwitch.retranslate()"
        assert f.consent.text() == shout(CONSENT)
    finally:
        QCoreApplication.removeTranslator(translator)
    qtbot.waitUntil(lambda: f.tagline.text() == TAGLINE, timeout=3000)
    assert f.name_error.text() == NAME_INVALID
    assert f.edit.text() == "w" * 65


def test_show_welcome_with_choice_restores_values(window, qtbot, tmp_path):
    from teleport.ui.first_run import FirstRunChoice

    suggested = tmp_path / "goi-y"
    chosen = tmp_path / "da-chon"
    c = FirstRunChoice(
        name_text="PC Nhà", name="PC Nhà", receive_dir=chosen, receive_dir_chosen=True, autostart=False
    )
    window.show_welcome("Laptop-Minh", suggested, autostart=True, choice=c)
    show_window(window, qtbot)
    f = form(window)
    assert f.edit.text() == "PC Nhà"
    assert window.first_run.receive_dir == chosen
    assert not f.switch.isChecked(), "khôi phục trạng thái công tắc của lần trước"
    again = choice_of(window)
    assert again.name == "PC Nhà"
    assert again.receive_dir == chosen and again.receive_dir_chosen is True
    assert again.autostart is False


def test_restore_recomputes_against_new_suggestion(window, qtbot, tmp_path):
    """14.4: sau lỗi RECEIVE_DIR tên đã được lưu, gợi ý mới = tên đó → gửi lại thì `name = None`;
    thư mục trùng thư mục gợi ý mới thì `receive_dir_chosen` False."""
    from teleport.ui.first_run import FirstRunChoice

    suggested = tmp_path / "goi-y"
    c = FirstRunChoice(
        name_text="PC Nhà", name="PC Nhà", receive_dir=suggested, receive_dir_chosen=True, autostart=True
    )
    window.show_welcome("PC Nhà", suggested, autostart=True, choice=c)
    again = choice_of(window)
    assert again.name_text == "PC Nhà"
    assert again.name is None, "chữ trùng gợi ý mới → None"
    assert again.receive_dir_chosen is False, "so lại với thư mục gợi ý mới"


def test_show_welcome_with_choice_and_dir_error_focuses_change_button(window, qtbot, tmp_path):
    from teleport.ui.first_run import FirstRunChoice
    from teleport.ui.receive_dir import ChangeError, change_error_text

    show_window(window, qtbot, active=True)
    bad = tmp_path / "la-file.txt"
    c = FirstRunChoice(
        name_text="Tên Đã Gõ", name="Tên Đã Gõ", receive_dir=bad, receive_dir_chosen=True, autostart=None
    )
    text = change_error_text(ChangeError.UNAVAILABLE, bad)
    window.show_welcome("Laptop-Minh", tmp_path / "goi-y", choice=c, dir_error=text)
    f = form(window)
    assert f.edit.text() == "Tên Đã Gõ"
    assert visible(f.dir_error, window) and f.dir_error.text() == text
    qtbot.waitUntil(lambda: focus() is f.dir_button, timeout=3000)


# =================================================================================================
# Hàm cấp module của `ui/app.py` (spec 5.6, Q2, Q5, 14.12)
# =================================================================================================


def test_suggested_device_name_uses_hostname(monkeypatch, tmp_path):
    from teleport.app import node as app_node
    from teleport.ui.app import suggested_device_name

    monkeypatch.setattr(app_node, "_hostname", lambda: "Laptop-Minh.local")
    assert suggested_device_name(tmp_path) == "Laptop-Minh"


@pytest.mark.parametrize("hostname", ["", "   ", "x" * 65, "May\x07A"], ids=["empty", "spaces", "65", "ctrl"])
def test_suggested_device_name_empty_when_fallback(monkeypatch, tmp_path, hostname):
    """Hostname không dùng được → tên dự phòng `Teleport-????` → gợi ý rỗng (không bao giờ điền sẵn)."""
    from teleport.app import node as app_node
    from teleport.ui.app import suggested_device_name

    monkeypatch.setattr(app_node, "_hostname", lambda: hostname)
    assert suggested_device_name(tmp_path) == ""


def test_suggested_device_name_prefers_saved_name(monkeypatch, tmp_path):
    from teleport.app import node as app_node
    from teleport.app.settings import Settings
    from teleport.ui.app import suggested_device_name

    monkeypatch.setattr(app_node, "_hostname", lambda: "Laptop-Minh")
    dataclasses.replace(Settings.load(tmp_path), name="PC Đã Lưu").save(tmp_path)
    before = (tmp_path / "settings.json").read_bytes()
    assert suggested_device_name(tmp_path) == "PC Đã Lưu"
    assert (tmp_path / "settings.json").read_bytes() == before, "chỉ đọc"


def test_suggested_device_name_survives_corrupt_settings(monkeypatch, tmp_path):
    from teleport.app import node as app_node
    from teleport.ui.app import suggested_device_name

    monkeypatch.setattr(app_node, "_hostname", lambda: "Laptop-Minh")
    (tmp_path / "settings.json").write_text("{không phải json", encoding="utf-8")
    assert suggested_device_name(tmp_path) == "Laptop-Minh"


class _MarkNode:
    def __init__(self, done: bool) -> None:
        self.settings = SimpleNamespace(first_run_done=done)
        self.prefs: list[dict] = []

    def set_ui_preferences(self, **kwargs):
        self.prefs.append(kwargs)


def test_mark_first_run_done_writes_only_when_false():
    from teleport.ui.app import _mark_first_run_done

    fresh = _MarkNode(False)
    _mark_first_run_done(fresh)
    assert fresh.prefs == [{"first_run_done": True}]

    done = _MarkNode(True)
    _mark_first_run_done(done)
    assert done.prefs == [], "đã True thì không ghi lại"


def test_retranslate_autostart_state_hint(window, qtbot, tmp_path):
    """14.14: `FirstRunForm.retranslate` dịch lại câu trạng thái của hàng tự khởi động (OTHER/BLOCKED).

    Câu này tới form qua `show_welcome(..., autostart_hint=str)` (đã dịch lúc dựng màn), nên form chỉ
    dịch lại được nếu tự nhớ nguồn của nó (hay app dựng lại câu khi đổi ngôn ngữ).
    """
    from teleport.app.autostart import AutostartState
    from teleport.ui.settings import autostart_state_hint

    hint = autostart_state_hint(AutostartState.OTHER)
    window.show_welcome("Laptop-Minh", tmp_path / "d", autostart=False, autostart_hint=hint)
    show_window(window, qtbot)
    f = form(window)
    translator = ShoutTranslator()
    QCoreApplication.installTranslator(translator)
    try:
        qtbot.waitUntil(lambda: f.tagline.text() == shout(TAGLINE), timeout=3000)
        assert f.autostart_state.text() == shout(hint), "câu trạng thái chưa được dịch lại"
    finally:
        QCoreApplication.removeTranslator(translator)
