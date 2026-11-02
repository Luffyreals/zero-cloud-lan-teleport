"""Phím tắt (`teleport.ui.shortcuts`) và chỗ dùng chúng: `MainWindow`, `ChatView`, tooltip, hàng “Phím tắt”
trong Cài đặt › Nâng cao (spec “phím tắt và dán file”, `plan-f-ux-hang-ngay F2`: mục 2, 4, 6 S1–S3,
S10–S14, S16–S19; mục 10 H6, H7, H8, H11, H13, H14 ghi đè khi khác).

Viết từ spec, không từ code. Phần dán file (S4–S9, S15, H1, H2, H12) ở `test_paste_files.py`.

- `WindowShortcut` chỉ chạy khi cửa sổ active (H11): test bấm phím đều kích hoạt cửa sổ trước.
- Phím Paste so với `QKeySequence.keyBindings(StandardKey.Paste)` lúc chạy (H11); phím khác so qua
  `NativeText` lúc chạy, nên câu như “Ctrl+N” vẫn đúng trên macOS (⌘N).
- Module `teleport.ui.*` chỉ import bên trong test/fixture.
"""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QPoint, Qt, QTranslator
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

NATIVE = QKeySequence.SequenceFormat.NativeText
PORTABLE = QKeySequence.SequenceFormat.PortableText

# Thứ tự `Shortcut` = thứ tự hàng của bảng (mục 2.1).
IDS = (
    "discover",
    "settings",
    "open_receive_dir",
    "go_to_conversation",
    "previous_conversation",
    "next_conversation",
    "pick_files",
    "paste_files",
    "back",
    "close_window",
    "quit",
    "retry",
)

# Phím đầu của mỗi id (PortableText), bảng mục 2.1. PASTE_FILES theo nền (H11), không viết cứng.
FIRST_KEY = {
    "discover": "Ctrl+N",
    "settings": "Ctrl+,",
    "open_receive_dir": "Ctrl+Shift+E",
    "go_to_conversation": "Ctrl+1",
    "previous_conversation": "Alt+Up",
    "next_conversation": "Alt+Down",
    "pick_files": "Ctrl+O",
    "back": "Esc",
    "close_window": "Ctrl+W",
    "quit": "Ctrl+Q",
    "retry": "F5",
}

# Mô tả tiếng Việt (mục 4; H8 cho PASTE_FILES; H14 cho CLOSE_WINDOW).
DESCRIBE_VI = {
    "discover": "Tìm máy mới",
    "settings": "Mở Cài đặt",
    "open_receive_dir": "Mở thư mục nhận",
    "go_to_conversation": "Mở cuộc trò chuyện thứ 1 đến 9 trong danh sách",
    "previous_conversation": "Chuyển lên cuộc trò chuyện phía trên",
    "next_conversation": "Chuyển xuống cuộc trò chuyện phía dưới",
    "pick_files": "Chọn file để gửi",
    "paste_files": "Gửi file đã chép trong {file_manager}",
    "back": "Quay lại",
    "close_window": "Đóng cửa sổ",
    "quit": "Thoát Teleport",
    "retry": "Thử lại khi Teleport không khởi động được",
}

SETTINGS_LABEL = "Phím tắt"
SETTINGS_HINT = "Dùng Teleport không cần chuột. Danh sách chỉ để xem, không đổi được phím."
COLUMNS = ("Thao tác", "Phím")
RETRY_TIP = "Khởi động lại Teleport ({key})"

# Chữ có dấu tiếng Việt (để kiểm bản English không còn câu nguồn).
_VI_CHARS = re.compile(r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.I)

PEER_A = "a1" * 16
PEER_B = "b2" * 16
PEER_C = "c3" * 16


# =================================================================================================
# Hàm phụ trợ
# =================================================================================================


def native(portable: str) -> str:
    return QKeySequence(portable).toString(NATIVE)


def paste_bindings() -> list[QKeySequence]:
    return list(QKeySequence.keyBindings(QKeySequence.StandardKey.Paste))


def settle(qtbot=None, ms: int = 0) -> None:
    for _ in range(3):
        QApplication.processEvents()
    if qtbot is not None and ms:
        qtbot.wait(ms)


def activate(qtbot, window: QWidget) -> None:
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    window.raise_()
    qtbot.waitUntil(window.isActiveWindow, timeout=3000)
    settle()


def press(target: QWidget | None, seq: QKeySequence | str) -> None:
    """Bấm tổ hợp đầu của `seq` vào `target` (None → widget đang có tiêu điểm)."""
    seq = QKeySequence(seq)
    combo = seq[0]
    widget = target if target is not None else QApplication.focusWidget()
    assert widget is not None, "không widget nào có tiêu điểm"
    QTest.keyClick(widget, combo.key(), combo.keyboardModifiers())
    settle()


def tip_text(tooltip: str) -> str:
    """Tooltip bỏ thẻ HTML (safe_tooltip bọc <qt>…</qt>), bỏ thoát HTML."""
    text = re.sub(r"<br\s*/?>", "\n", tooltip, flags=re.IGNORECASE)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def record(signal) -> list:
    seen: list = []
    signal.connect(lambda *a: seen.append(a[0] if len(a) == 1 else a))
    return seen


def dview(device_id: str, name: str, *, online: bool = True, paired: bool = True):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id,
        name=name,
        os="windows",
        paired=paired,
        online=online,
        connected=online and paired,
        addresses=("192.168.1.20",) if online else (),
        port=47474 if online else None,
    )


def dummy_page(label: str) -> tuple[QWidget, QPushButton]:
    """Trang mẫu (như `test_pages._page`): một nút, trang đặt `setFocusProxy` tới nút."""
    page = QWidget()
    lay = QVBoxLayout(page)
    button = QPushButton(f"Nút của trang {label}")
    lay.addWidget(button)
    page.setFocusProxy(button)
    return page, button


class KeyRecorder(QPushButton):
    """Nút ghi lại mọi phím nó nhận được (kiểm phím đi tiếp tới widget khi action tắt)."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.keys: list[tuple[int, Qt.KeyboardModifier]] = []

    def keyPressEvent(self, event) -> None:
        self.keys.append((event.key(), event.modifiers()))
        super().keyPressEvent(event)


class ContextPrefixTranslator(QTranslator):
    """Dịch mọi chuỗi của một ngữ cảnh bằng cách thêm tiền tố (kiểm ngữ cảnh `Shortcuts`, dịch lúc gọi)."""

    def __init__(self, context: str, prefix: str) -> None:
        super().__init__()
        self.context = context
        self.prefix = prefix

    def isEmpty(self) -> bool:
        return False

    def translate(self, context, source_text, disambiguation=None, n=-1):
        if context == self.context and source_text:
            return self.prefix + source_text
        return None


class FakeHost:
    """`NodeHost` giả cho `TransfersController.attach` (không node, không socket)."""

    def __init__(self, receive_dir: Path) -> None:
        from teleport.ui.bridge import NodeOptions

        self.options = NodeOptions(config_dir=receive_dir.parent / "cfg", receive_dir=receive_dir, mdns=None)
        self.calls: list = []
        self.submits: list = []
        self.running = True
        self.is_stopped = False
        self.node_name = "May-A"

    def call(self, fn, on_done=None) -> None:
        self.calls.append((fn, on_done))

    def submit(self, fn, on_done=None) -> None:
        self.submits.append((fn, on_done))


# =================================================================================================
# Fixture
# =================================================================================================


@pytest.fixture
def window(qtbot):
    from teleport.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(980, 660)
    return w


@pytest.fixture
def full(qtbot, monkeypatch, tmp_path):
    """`MainWindow` + `TransfersController` (có `ChatView` thật) với `NodeHost` giả, như `GuiApp` dựng."""
    from teleport.ui import transfers as mod
    from teleport.ui.main_window import MainWindow
    from teleport.ui.tray import Tray

    monkeypatch.setattr(Tray, "show_message", lambda self, text, folder=None: None)
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(980, 660)
    tray = Tray()
    ctl = mod.TransfersController(w, tray, parent=None)
    ctl.attach(FakeHost(tmp_path / "nhan"))
    yield SimpleNamespace(window=w, ctl=ctl, view=ctl.view, tmp=tmp_path)
    ctl.close_all()
    tray.dispose()


@pytest.fixture
def three(window, qtbot, tmp_path):
    """Cửa sổ RUNNING, ba máy đã ghép đôi, đang active; trả cả thứ tự đang hiện của danh sách."""
    from teleport.ui.conversations import DEVICE_ID_ROLE

    window.show_running("May-A", tmp_path / "nhan")
    window.devices.reset([dview(PEER_A, "PC-A"), dview(PEER_B, "PC-B"), dview(PEER_C, "PC-C")])
    activate(qtbot, window)
    model = window.conversations.model
    order = [model.index(r, 0).data(DEVICE_ID_ROLE) for r in range(model.rowCount())]
    assert sorted(order) == sorted([PEER_A, PEER_B, PEER_C]), order
    return SimpleNamespace(window=window, conv=window.conversations, order=order)


def selected(conv) -> str | None:
    d = conv.current_device()
    return None if d is None else d.device_id


# =================================================================================================
# `ui.shortcuts`: danh sách (S1, S3, H11, H13)
# =================================================================================================


def test_shortcut_ids_and_table_order():
    from teleport.ui.shortcuts import SHORTCUTS, Shortcut, info

    assert [s.value for s in Shortcut] == list(IDS)
    assert [entry.id for entry in SHORTCUTS] == list(Shortcut), "thứ tự SHORTCUTS = thứ tự bảng (mục 2.1)"
    for s in Shortcut:
        assert info(s).id is s


def test_first_key_of_each_shortcut_matches_table():
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    for name, portable in FIRST_KEY.items():
        s = Shortcut(name)
        assert shortcuts.sequence(s) == QKeySequence(portable), name
        assert shortcuts.portable_text(s) == portable, name
        assert shortcuts.sequences(s)[0] == QKeySequence(portable), name


def test_go_to_conversation_has_ctrl_1_to_9():
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    assert shortcuts.sequences(Shortcut.GO_TO_CONVERSATION) == [
        QKeySequence(f"Ctrl+{i}") for i in range(1, 10)
    ]


@pytest.mark.parametrize("name", [n for n in IDS if n not in ("go_to_conversation", "paste_files")])
def test_other_shortcuts_have_exactly_one_key(name):
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    assert shortcuts.sequences(Shortcut(name)) == [QKeySequence(FIRST_KEY[name])]


def test_paste_keys_are_platform_standard_paste():
    """H11: Paste là `StandardKey.Paste`, tính lúc gọi (Windows: Ctrl+V và Shift+Ins)."""
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    assert shortcuts.info(Shortcut.PASTE_FILES).keys == (QKeySequence.StandardKey.Paste,)
    expected = paste_bindings()
    assert expected, "nền không có phím Paste"
    assert shortcuts.sequences(Shortcut.PASTE_FILES) == expected
    assert shortcuts.sequence(Shortcut.PASTE_FILES) == expected[0]


def _all_keys() -> dict[str, list[str]]:
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    return {s.value: [q.toString(PORTABLE) for q in shortcuts.sequences(s)] for s in Shortcut}


def test_s1_no_two_shortcuts_share_a_key():
    owners: dict[str, list[str]] = {}
    for name, keys in _all_keys().items():
        for key in keys:
            owners.setdefault(key, []).append(name)
    shared = {k: v for k, v in owners.items() if len(v) > 1}
    assert shared == {}


def test_s1_no_key_uses_ctrl_alt_or_meta():
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    ctrl = Qt.KeyboardModifier.ControlModifier
    alt = Qt.KeyboardModifier.AltModifier
    meta = Qt.KeyboardModifier.MetaModifier
    for s in Shortcut:
        for seq in shortcuts.sequences(s):
            assert not seq.isEmpty(), s
            for i in range(seq.count()):
                mods = seq[i].keyboardModifiers()
                assert not (mods & ctrl and mods & alt), f"{s}: {seq.toString(PORTABLE)} dùng Ctrl+Alt/AltGr"
                assert not (mods & meta), f"{s}: {seq.toString(PORTABLE)} dùng Meta"


def test_no_shortcut_takes_a_line_edit_editing_key_except_paste():
    """Quy tắc mục 2.1: không trùng phím soạn thảo chuẩn của ô nhập, trừ Paste (nhường có chủ đích)."""
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    sk = QKeySequence.StandardKey
    editing = [
        sk.Copy,
        sk.Cut,
        sk.Undo,
        sk.Redo,
        sk.SelectAll,
        sk.Delete,
        sk.Backspace,
        sk.DeleteStartOfWord,
        sk.DeleteEndOfWord,
        sk.DeleteEndOfLine,
        sk.DeleteCompleteLine,
        sk.MoveToNextChar,
        sk.MoveToPreviousChar,
        sk.MoveToNextWord,
        sk.MoveToPreviousWord,
        sk.MoveToStartOfLine,
        sk.MoveToEndOfLine,
        sk.SelectNextChar,
        sk.SelectPreviousChar,
        sk.SelectNextWord,
        sk.SelectPreviousWord,
        sk.SelectStartOfLine,
        sk.SelectEndOfLine,
    ]
    taken = {q.toString(PORTABLE) for key in editing for q in QKeySequence.keyBindings(key)}
    for s in Shortcut:
        if s is Shortcut.PASTE_FILES:
            continue
        clash = [q.toString(PORTABLE) for q in shortcuts.sequences(s) if q.toString(PORTABLE) in taken]
        assert clash == [], f"{s} trùng phím soạn thảo {clash}"


def test_s3_key_text_go_to_conversation_is_range():
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    expected = f"{native('Ctrl+1')} đến {native('Ctrl+9')}"
    assert shortcuts.key_text(Shortcut.GO_TO_CONVERSATION) == expected
    if sys.platform == "win32":
        assert shortcuts.key_text(Shortcut.GO_TO_CONVERSATION) == "Ctrl+1 đến Ctrl+9"


def test_key_text_is_native_text_of_first_key():
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    for name, portable in FIRST_KEY.items():
        if name == "go_to_conversation":
            continue
        assert shortcuts.key_text(Shortcut(name)) == native(portable), name
    assert shortcuts.key_text(Shortcut.PASTE_FILES) == paste_bindings()[0].toString(NATIVE)


def _describe_vi() -> dict[str, str]:
    from teleport.ui import texts

    fm = texts.file_manager_name()
    return {k: v.replace("{file_manager}", fm) for k, v in DESCRIBE_VI.items()}


def test_describe_vietnamese_texts():
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    expected = _describe_vi()
    for s in Shortcut:
        assert shortcuts.describe(s) == expected[s.value], s
        assert shortcuts.info(s).describe() == expected[s.value], s


def test_s3_table_rows_twelve_in_order():
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    rows = shortcuts.table_rows()
    expected = _describe_vi()
    assert len(rows) == 12
    assert rows == [(expected[s.value], shortcuts.key_text(s)) for s in Shortcut]


def test_q5_table_does_not_list_shift_insert():
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    keys = dict(shortcuts.table_rows())
    paste = keys[shortcuts.describe(Shortcut.PASTE_FILES)]
    assert paste == paste_bindings()[0].toString(NATIVE)
    assert "Ins" not in paste


def test_file_manager_name_follows_os():
    """H8: Windows “File Explorer”, macOS “Finder”, khác “trình quản lý file”."""
    from teleport.ui import texts

    expected = {"win32": "File Explorer", "darwin": "Finder"}.get(sys.platform, "trình quản lý file")
    assert texts.file_manager_name() == expected


def test_describe_is_translated_at_call_time_in_shortcuts_context():
    """H13: `describe` gọi `QCoreApplication.translate("Shortcuts", …)` lúc gọi."""
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    translator = ContextPrefixTranslator("Shortcuts", "[sc]")
    QCoreApplication.installTranslator(translator)
    try:
        for s in Shortcut:
            assert shortcuts.describe(s).startswith("[sc]"), s
    finally:
        QCoreApplication.removeTranslator(translator)
    for s in Shortcut:
        assert not shortcuts.describe(s).startswith("[sc]"), s


def test_s3_english_descriptions(qapp):
    from teleport.ui import i18n, shortcuts
    from teleport.ui.shortcuts import Shortcut

    vi = {s: shortcuts.describe(s) for s in Shortcut}
    i18n.set_language("en")
    settle()
    assert i18n.current_language() == "en", "không nạp được teleport_en.qm"
    for s in Shortcut:
        text = shortcuts.describe(s)
        assert text and text != vi[s], f"{s} chưa dịch: {text!r}"
        assert not _VI_CHARS.search(text), f"{s} còn chữ tiếng Việt: {text!r}"
    rows = shortcuts.table_rows()
    assert [d for d, _ in rows] == [shortcuts.describe(s) for s in Shortcut]
    assert not _VI_CHARS.search(rows[3][1]), f"khoảng phím chưa dịch: {rows[3][1]!r}"


def test_import_does_not_need_a_gui_application(tmp_path):
    """H13: `sequences()` cho StandardKey chỉ tính lúc gọi; import module khi chưa có QGuiApplication không
    lỗi và chưa tính phím Paste."""
    src = Path(__file__).resolve().parents[2] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    env["QT_QPA_PLATFORM"] = "offscreen"
    code = (
        "from PySide6.QtCore import QCoreApplication\n"
        "from PySide6.QtGui import QKeySequence\n"
        "import teleport.ui.shortcuts as s\n"
        "assert QCoreApplication.instance() is None\n"
        "assert s.info(s.Shortcut.PASTE_FILES).keys == (QKeySequence.StandardKey.Paste,)\n"
        "print('ok')\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60, cwd=tmp_path
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().endswith("ok")


# =================================================================================================
# `make_action`, `retranslate_actions`
# =================================================================================================


def test_make_action_sets_keys_context_text_data_and_parent(qtbot):
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    host = QWidget()
    qtbot.addWidget(host)
    calls: list[int] = []
    action = shortcuts.make_action(host, Shortcut.DISCOVER, lambda: calls.append(1))
    assert isinstance(action, QAction)
    assert action in host.actions()
    assert action.shortcuts() == shortcuts.sequences(Shortcut.DISCOVER)
    assert action.shortcutContext() == Qt.ShortcutContext.WindowShortcut
    assert action.autoRepeat() is False
    assert action.text() == shortcuts.describe(Shortcut.DISCOVER)
    assert action.data() == "discover"
    action.trigger()
    assert calls == [1]


def test_make_action_keys_override_and_auto_repeat(qtbot):
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    host = QWidget()
    qtbot.addWidget(host)
    one = shortcuts.make_action(
        host, Shortcut.GO_TO_CONVERSATION, lambda: None, keys=[QKeySequence("Ctrl+3")], auto_repeat=True
    )
    assert one.shortcuts() == [QKeySequence("Ctrl+3")]
    assert one.autoRepeat() is True
    paste = shortcuts.make_action(host, Shortcut.PASTE_FILES, lambda: None)
    assert paste.shortcuts() == paste_bindings()


def test_retranslate_actions_only_touches_shortcut_actions(qtbot):
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    host = QWidget()
    qtbot.addWidget(host)
    action = shortcuts.make_action(host, Shortcut.QUIT, lambda: None)
    other = QAction("Không phải phím tắt", host)
    host.addAction(other)
    translator = ContextPrefixTranslator("Shortcuts", "[sc]")
    QCoreApplication.installTranslator(translator)
    try:
        shortcuts.retranslate_actions(host)
        assert action.text() == "[sc]" + DESCRIBE_VI["quit"]
        assert other.text() == "Không phải phím tắt"
    finally:
        QCoreApplication.removeTranslator(translator)
    shortcuts.retranslate_actions(host)
    assert action.text() == DESCRIBE_VI["quit"]


# =================================================================================================
# MainWindow: tên action, S2, tự lặp
# =================================================================================================


def test_main_window_action_names(window):
    from teleport.ui.main_window import SETTINGS_SHORTCUT

    assert SETTINGS_SHORTCUT == "Ctrl+,"
    for name in (
        "_retry_action",
        "_close_action",
        "_quit_action",
        "_back_action",
        "_settings_action",
        "_discover_action",
        "_open_dir_action",
        "_previous_action",
        "_next_action",
    ):
        assert isinstance(getattr(window, name), QAction), name
    actions = window._conversation_actions
    assert len(actions) == 9
    assert [a.shortcuts() for a in actions] == [[QKeySequence(f"Ctrl+{i}")] for i in range(1, 10)]
    assert window._discover_action.shortcuts() == [QKeySequence("Ctrl+N")]
    assert window._open_dir_action.shortcuts() == [QKeySequence("Ctrl+Shift+E")]
    assert window._previous_action.shortcuts() == [QKeySequence("Alt+Up")]
    assert window._next_action.shortcuts() == [QKeySequence("Alt+Down")]


def _keyed_actions(owner: QWidget) -> list[QAction]:
    return [a for a in owner.actions() if isinstance(a, QAction) and a.shortcuts()]


def test_s2_every_window_and_chat_key_belongs_to_one_shortcut_once(full):
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    w, view = full.window, full.view
    assert w.isAncestorOf(view), "ChatView nằm trong cửa sổ chính"
    keys_of = {s: {q.toString(PORTABLE) for q in shortcuts.sequences(s)} for s in Shortcut}
    on_window = _keyed_actions(w)
    on_view = _keyed_actions(view)
    seen: Counter[str] = Counter()
    for owner, actions in (("MainWindow", on_window), ("ChatView", on_view)):
        for action in actions:
            mine = {q.toString(PORTABLE) for q in action.shortcuts()}
            ids = [s for s in Shortcut if mine <= keys_of[s]]
            assert len(ids) == 1, f"{owner}: action {action.text()!r} {sorted(mine)} thuộc {ids}"
            assert action.shortcutContext() == Qt.ShortcutContext.WindowShortcut, action.text()
            expected_owner = (
                "ChatView" if ids[0] in (Shortcut.PICK_FILES, Shortcut.PASTE_FILES) else "MainWindow"
            )
            assert owner == expected_owner, f"{ids[0]} phải gắn ở {expected_owner}"
            seen.update(mine)
    assert {k: n for k, n in seen.items() if n > 1} == {}, "một phím chỉ thuộc đúng một action"
    every_key = set().union(*keys_of.values())
    assert set(seen) == every_key, f"phím chưa có action: {sorted(every_key - set(seen))}"


def test_auto_repeat_only_for_previous_and_next(full):
    w, view = full.window, full.view
    assert view._paste_action.autoRepeat() is False, "giữ Ctrl+V không gửi nhiều lần (H11)"
    assert view._pick_action.autoRepeat() is False
    repeating = {w._previous_action, w._next_action}
    for action in _keyed_actions(w) + _keyed_actions(view):
        assert action.autoRepeat() is (action in repeating), action.text()


def test_window_action_texts_are_descriptions(full):
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    w, view = full.window, full.view
    pairs = {
        w._discover_action: Shortcut.DISCOVER,
        w._settings_action: Shortcut.SETTINGS,
        w._open_dir_action: Shortcut.OPEN_RECEIVE_DIR,
        w._previous_action: Shortcut.PREVIOUS_CONVERSATION,
        w._next_action: Shortcut.NEXT_CONVERSATION,
        w._back_action: Shortcut.BACK,
        w._close_action: Shortcut.CLOSE_WINDOW,
        w._quit_action: Shortcut.QUIT,
        w._retry_action: Shortcut.RETRY,
        view._pick_action: Shortcut.PICK_FILES,
        view._paste_action: Shortcut.PASTE_FILES,
    }
    for action, s in pairs.items():
        assert action.text() == shortcuts.describe(s), s
        assert action.data() == s.value, s
    for action in w._conversation_actions:
        assert action.data() == Shortcut.GO_TO_CONVERSATION.value


# =================================================================================================
# S10, S11: Ctrl+N, Ctrl+,
# =================================================================================================


def test_s10_ctrl_n_from_home_opens_discover(window, qtbot, tmp_path):
    from teleport.ui.main_window import Page

    window.show_running("May-A", tmp_path / "nhan")
    activate(qtbot, window)
    assert window._discover_action.isEnabled()
    seen = record(window.page_changed)
    press(None, "Ctrl+N")
    assert window.current_page is Page.DISCOVER
    assert seen == ["discover"]


def test_s10_ctrl_n_from_settings_opens_discover(window, qtbot, tmp_path):
    from teleport.ui.main_window import Page

    page, _ = dummy_page("S")
    window.add_page(Page.SETTINGS, page)
    window.show_running("May-A", tmp_path / "nhan")
    activate(qtbot, window)
    assert window.open_page(Page.SETTINGS)
    settle()
    press(None, "Ctrl+N")
    assert window.current_page is Page.DISCOVER


@pytest.mark.parametrize("state", ["welcome", "starting", "error"])
def test_s10_ctrl_n_does_nothing_outside_running(window, qtbot, state):
    from teleport.ui.main_window import Page

    {
        "welcome": lambda: window.show_welcome("May-A"),
        "starting": window.show_starting,
        "error": lambda: window.show_error("other", ""),
    }[state]()
    activate(qtbot, window)
    assert window._discover_action.isEnabled() is False
    seen = record(window.page_changed)
    press(window, "Ctrl+N")
    assert window.current_page is Page.HOME
    assert seen == []


def test_s11_ctrl_comma_opens_settings(window, qtbot, tmp_path):
    from teleport.ui.main_window import Page

    page, _ = dummy_page("S")
    window.add_page(Page.SETTINGS, page)
    window.show_running("May-A", tmp_path / "nhan")
    activate(qtbot, window)
    assert window._settings_action.isEnabled()
    press(None, "Ctrl+,")
    assert window.current_page is Page.SETTINGS


def test_settings_action_enabled_only_with_settings_page_when_running(window, tmp_path):
    from teleport.ui.main_window import Page

    window.show_running("May-A", tmp_path / "nhan")
    assert window._settings_action.isEnabled() is False, "chưa có trang SETTINGS"
    page, _ = dummy_page("S")
    window.add_page(Page.SETTINGS, page)
    assert window._settings_action.isEnabled() is True, "add_page gọi _update_shortcuts"
    window.show_error("other", "")
    assert window._settings_action.isEnabled() is False


def test_always_on_actions_stay_enabled(window, tmp_path):
    for setup in (
        lambda: None,
        lambda: window.show_welcome("May-A"),
        window.show_starting,
        lambda: window.show_error("other", ""),
        lambda: window.show_running("May-A", tmp_path / "nhan"),
    ):
        setup()
        for action in (window._close_action, window._quit_action, window._retry_action):
            assert action.isEnabled(), action.text()


# =================================================================================================
# S12: Ctrl+1…9, Alt+↑/↓
# =================================================================================================


def test_device_id_at_follows_shown_order(three):
    conv, order = three.conv, three.order
    assert [conv.device_id_at(r) for r in range(3)] == order
    assert conv.device_id_at(3) is None
    assert conv.device_id_at(-1) is None


def test_neighbor_id_clamps_at_both_ends(three):
    conv, order = three.conv, three.order
    conv.select_device(order[0])
    settle()
    assert conv.neighbor_id(1) == order[1]
    assert conv.neighbor_id(-1) is None
    conv.select_device(order[2])
    settle()
    assert conv.neighbor_id(-1) == order[1]
    assert conv.neighbor_id(1) is None


def test_neighbor_id_without_selection_goes_to_first_or_last(three):
    conv, order = three.conv, three.order
    lst = conv.list_view
    lst.selectionModel().clear()
    settle()
    assert conv.current_device() is None, "dựng ca chưa chọn máy: phải bỏ chọn được"
    assert conv.neighbor_id(1) == order[0]
    assert conv.neighbor_id(-1) == order[2]


def test_neighbor_id_on_empty_list_is_none(window, tmp_path):
    window.show_running("May-A", tmp_path / "nhan")
    assert window.conversations.neighbor_id(1) is None
    assert window.conversations.neighbor_id(-1) is None
    assert window.conversations.device_id_at(0) is None


def test_s12_ctrl_2_selects_second_row_and_focuses_list(three):
    w, conv, order = three.window, three.conv, three.order
    w.discover_button.setFocus(Qt.FocusReason.OtherFocusReason)
    settle()
    press(None, "Ctrl+2")
    assert selected(conv) == order[1]
    assert QApplication.focusWidget() is conv.list_view, "Q3: tiêu điểm ở danh sách"


def test_s12_ctrl_9_beyond_list_changes_nothing(three):
    w, conv, order = three.window, three.conv, three.order
    conv.select_device(order[1])
    settle()
    press(None, "Ctrl+9")
    assert selected(conv) == order[1]
    assert w.open_conversation_at(8) is False
    assert w.open_conversation_at(2) is True
    assert selected(conv) == order[2]


def test_s12_alt_down_up_move_one_row_and_stop_at_ends(three):
    conv, order = three.conv, three.order
    conv.select_device(order[0])
    conv.list_view.setFocus(Qt.FocusReason.OtherFocusReason)
    settle()
    press(None, "Alt+Down")
    assert selected(conv) == order[1]
    press(None, "Alt+Down")
    assert selected(conv) == order[2]
    press(None, "Alt+Down")
    assert selected(conv) == order[2], "không vòng (Q4)"
    press(None, "Alt+Up")
    assert selected(conv) == order[1]
    press(None, "Alt+Up")
    press(None, "Alt+Up")
    assert selected(conv) == order[0], "không vòng (Q4)"
    assert QApplication.focusWidget() is conv.list_view


def test_step_conversation_api(three):
    w, conv, order = three.window, three.conv, three.order
    conv.select_device(order[2])
    settle()
    assert w.step_conversation(1) is False
    assert selected(conv) == order[2]
    assert w.step_conversation(-1) is True
    assert selected(conv) == order[1]


def test_s12_conversation_actions_only_on_home(three, tmp_path):
    from teleport.ui.main_window import Page

    w = three.window
    for action in (*w._conversation_actions, w._previous_action, w._next_action):
        assert action.isEnabled(), action.text()
    assert w.open_page(Page.DISCOVER)
    settle()
    for action in (*w._conversation_actions, w._previous_action, w._next_action):
        assert action.isEnabled() is False, action.text()
    w.go_back()
    settle()
    for action in (*w._conversation_actions, w._previous_action, w._next_action):
        assert action.isEnabled(), action.text()


def test_s12_alt_down_on_settings_reaches_widget(three):
    from teleport.ui.main_window import Page

    w, conv, order = three.window, three.conv, three.order
    page = QWidget()
    recorder = KeyRecorder("Ghi phím")
    QVBoxLayout(page).addWidget(recorder)
    page.setFocusProxy(recorder)
    w.add_page(Page.SETTINGS, page)
    conv.select_device(order[0])
    settle()
    assert w.open_page(Page.SETTINGS)
    recorder.setFocus(Qt.FocusReason.OtherFocusReason)
    settle()
    assert QApplication.focusWidget() is recorder
    assert w._next_action.isEnabled() is False
    press(recorder, "Alt+Down")
    press(recorder, "Ctrl+2")
    assert (Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier) in [(Qt.Key(k), m) for k, m in recorder.keys], (
        "Alt+↓ phải tới widget khi action tắt"
    )
    assert w.current_page is Page.SETTINGS
    assert selected(conv) == order[0]


@pytest.mark.parametrize("state", ["welcome", "starting", "error"])
def test_s12_conversation_actions_off_outside_running(window, state):
    {
        "welcome": lambda: window.show_welcome("May-A"),
        "starting": window.show_starting,
        "error": lambda: window.show_error("other", ""),
    }[state]()
    for action in (*window._conversation_actions, window._previous_action, window._next_action):
        assert action.isEnabled() is False, action.text()


# =================================================================================================
# S13: Ctrl+Shift+E
# =================================================================================================


def test_s13_ctrl_shift_e_opens_receive_dir_once(window, qtbot, tmp_path):
    receive = tmp_path / "nhan"
    window.show_running("May-A", receive)
    activate(qtbot, window)
    assert window._open_dir_action.isEnabled()
    seen = record(window.open_receive_dir_requested)
    press(None, "Ctrl+Shift+E")
    assert seen == [receive]


def test_s13_ctrl_shift_e_works_on_other_pages(window, qtbot, tmp_path):
    from teleport.ui.main_window import Page

    receive = tmp_path / "nhan"
    window.show_running("May-A", receive)
    activate(qtbot, window)
    assert window.open_page(Page.DISCOVER)
    settle()
    seen = record(window.open_receive_dir_requested)
    press(None, "Ctrl+Shift+E")
    assert seen == [receive]


def test_s13_open_dir_action_off_without_receive_dir(window, qtbot, tmp_path):
    window.show_running("May-A", None)
    activate(qtbot, window)
    assert window._open_dir_action.isEnabled() is False
    seen = record(window.open_receive_dir_requested)
    press(window.focusWidget() or window, "Ctrl+Shift+E")
    assert seen == []
    window.set_receive_dir(tmp_path / "moi")
    assert window._open_dir_action.isEnabled() is True
    window.set_receive_dir(None)
    assert window._open_dir_action.isEnabled() is False


@pytest.mark.parametrize("state", ["welcome", "starting", "error"])
def test_s13_open_dir_action_off_outside_running(window, tmp_path, state):
    window.show_running("May-A", tmp_path / "nhan")
    {
        "welcome": lambda: window.show_welcome("May-A", tmp_path / "nhan"),
        "starting": window.show_starting,
        "error": lambda: window.show_error("other", ""),
    }[state]()
    assert window._open_dir_action.isEnabled() is False


# =================================================================================================
# S14: hộp thoại không bị cửa sổ chính bắt phím
# =================================================================================================


def test_s14_child_dialog_keys_do_not_reach_main_window(full, qtbot, monkeypatch):
    from PySide6.QtCore import QMimeData, QUrl

    from teleport.ui import chat
    from teleport.ui.main_window import Page

    w, view = full.window, full.view
    w.show_running("May-A", full.tmp / "nhan")
    w.devices.reset([dview(PEER_A, "PC-A"), dview(PEER_B, "PC-B")])
    activate(qtbot, w)
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(full.tmp / "a.txt"))])
    monkeypatch.setattr(chat, "_clipboard_mime", lambda: data)
    sends = record(view.send_files_requested)
    pages = record(w.page_changed)
    before = selected(w.conversations)
    assert before is not None
    second = w.conversations.device_id_at(1)

    dialog = QDialog(w)
    dialog.setLayout(QVBoxLayout())
    ok = QPushButton("OK")
    dialog.layout().addWidget(ok)
    activate(qtbot, dialog)
    ok.setFocus()
    settle()
    for seq in (paste_bindings()[0], QKeySequence("Ctrl+N"), QKeySequence("Ctrl+2")):
        press(ok, seq)
    assert sends == []
    assert view.notice_text() == ""
    assert pages == []
    assert w.current_page is Page.HOME
    assert selected(w.conversations) == before != second
    dialog.close()


# =================================================================================================
# S16: tooltip ghi kèm phím, nhãn và tên trợ năng không
# =================================================================================================


def _no_key(widget, key: str) -> None:
    label = getattr(widget, "label", None)
    for text in (plain(widget.text()), widget.accessibleName(), label if isinstance(label, str) else ""):
        assert key not in text, f"{widget.objectName()}: {text!r} chứa phím {key!r}"


def test_s16_tooltips_include_keys_labels_do_not(full, tmp_path):
    w, view = full.window, full.view
    w.show_running("May-A", tmp_path / "nhan")
    w.devices.reset([dview(PEER_A, "PC-A")])
    settle()
    ctrl_n, ctrl_comma = native("Ctrl+N"), native("Ctrl+,")
    open_key, pick_key, esc = native("Ctrl+Shift+E"), native("Ctrl+O"), native("Esc")

    assert tip_text(w.discover_button.toolTip()) == f"Tìm máy mới ({ctrl_n})"
    assert tip_text(w.settings_button.toolTip()) == f"Cài đặt ({ctrl_comma})"
    assert tip_text(w.conversations.add_button.toolTip()).endswith(f"({ctrl_n})")
    assert tip_text(w.save_bar.open_button.toolTip()) == f"Mở thư mục ({open_key})"
    assert f"({pick_key})" in tip_text(view.composer.send_button.toolTip())
    back = w.discover.header.back_button
    assert f"({esc})" in tip_text(back.toolTip())
    assert tip_text(w.retry_button.toolTip()) == RETRY_TIP.format(key=native("F5"))

    for widget, key in (
        (w.discover_button, ctrl_n),
        (w.settings_button, ctrl_comma),
        (w.conversations.add_button, ctrl_n),
        (w.save_bar.open_button, open_key),
        (view.composer.send_button, pick_key),
        (back, esc),
        (w.retry_button, native("F5")),
    ):
        _no_key(widget, key)


def test_s16_retry_tooltip_follows_language(window, qapp):
    from teleport.ui import i18n

    window.show_error("other", "")
    vi = tip_text(window.retry_button.toolTip())
    assert vi == RETRY_TIP.format(key=native("F5"))
    i18n.set_language("en")
    settle()
    en = tip_text(window.retry_button.toolTip())
    assert en != vi and native("F5") in en and not _VI_CHARS.search(en)


# =================================================================================================
# S19: đổi ngôn ngữ, text QAction đổi theo
# =================================================================================================


def test_s19_action_texts_follow_language(full, qapp):
    from teleport.ui import i18n, shortcuts
    from teleport.ui.shortcuts import Shortcut

    w, view = full.window, full.view
    vi_discover = w._discover_action.text()
    vi_paste = view._paste_action.text()
    i18n.set_language("en")
    settle()
    assert i18n.current_language() == "en"
    assert w._discover_action.text() == shortcuts.describe(Shortcut.DISCOVER) != vi_discover
    assert view._paste_action.text() == shortcuts.describe(Shortcut.PASTE_FILES) != vi_paste
    assert w._conversation_actions[0].text() == shortcuts.describe(Shortcut.GO_TO_CONVERSATION)
    i18n.set_language("vi")
    settle()
    assert w._discover_action.text() == vi_discover


# =================================================================================================
# S17, S17b, S18, S19: hàng “Phím tắt” trong Cài đặt › Nâng cao
# =================================================================================================


def _snapshot():
    from teleport.ui.settings import SettingsSnapshot

    return SettingsSnapshot(
        name="May-A",
        visible=True,
        rate_limit=None,
        temp_retention_days=None,
        language=None,
        autostart=False,
        devices={},
    )


def _settings_page(qtbot, *, size=(980, 660)):
    from teleport.app.autostart import AutostartState
    from teleport.ui.radar import DeviceListModel
    from teleport.ui.settings import Section, SettingsPage

    model = DeviceListModel()
    page = SettingsPage(model)
    model.setParent(page)
    qtbot.addWidget(page)
    page.resize(*size)
    page.set_loaded(True)
    page.set_values(_snapshot())
    page.set_language(None, ("vi",))
    page.set_autostart(AutostartState.OFF)
    activate(qtbot, page)
    page.show_section(Section.ADVANCED)
    settle(qtbot, 30)
    return page


@pytest.fixture
def advanced(qtbot):
    return _settings_page(qtbot)


@pytest.fixture
def with_notices(monkeypatch, tmp_path):
    """Nút “Thông báo bên thứ ba” hiện (có file cạnh `sys.executable`)."""
    exe = tmp_path / "Teleport.exe"
    exe.write_bytes(b"")
    (tmp_path / "THIRD-PARTY-NOTICES.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe))


def test_s17_shortcuts_row_and_table_structure(advanced):
    page = advanced
    table = page.shortcuts_table
    assert page.shortcuts_row.objectName() == "shortcutsRow"
    assert isinstance(table, QTableWidget)
    assert table.objectName() == "shortcutsTable"
    assert page.shortcuts_row.isAncestorOf(table)
    assert table.rowCount() == 12
    assert table.columnCount() == 2
    assert table.isVisibleTo(page)
    assert [table.horizontalHeaderItem(c).text() for c in range(2)] == list(COLUMNS)
    assert table.verticalHeader().isHidden()
    assert table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert table.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    assert table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert table.alternatingRowColors() is False
    assert table.tabKeyNavigation() is False, "H6"
    assert table.wordWrap() is True, "H7"
    assert table.textElideMode() == Qt.TextElideMode.ElideNone, "H7"
    header = table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.ResizeToContents
    policy = int(table.focusPolicy().value)
    assert policy & int(Qt.FocusPolicy.TabFocus.value), "Tab vào bảng được"
    assert policy & int(Qt.FocusPolicy.ClickFocus.value), "bấm vào bảng được"
    assert not policy & 0x4, "bánh xe chuột không lấy tiêu điểm (TabFocus|ClickFocus)"


def test_s17_table_has_no_scrollbars_and_fits_rows(advanced):
    table = advanced.shortcuts_table
    for bar in (table.verticalScrollBar(), table.horizontalScrollBar()):
        assert not bar.isVisible()
        assert bar.maximum() == 0, "cao/rộng vừa đúng: không có gì để cuộn"
    last = table.visualRect(table.model().index(table.rowCount() - 1, 0))
    assert last.bottom() <= table.viewport().height()


def test_s17_table_content_matches_table_rows(advanced):
    from teleport.ui import shortcuts

    table = advanced.shortcuts_table
    rows = shortcuts.table_rows()
    role = Qt.ItemDataRole.AccessibleTextRole
    for r, (describe, key) in enumerate(rows):
        first, second = table.item(r, 0), table.item(r, 1)
        assert first.text() == describe
        assert second.text() == key
        assert first.data(role) == f"{describe}: {key}"
        assert second.data(role) == key
        for item in (first, second):
            assert not item.flags() & Qt.ItemFlag.ItemIsEditable


def test_s17_accessibility_and_row_texts(advanced):
    page = advanced
    table = page.shortcuts_table
    assert table.accessibleName() == SETTINGS_LABEL
    assert table.accessibleDescription() == SETTINGS_HINT
    texts = [lb.text() for lb in page.shortcuts_row.findChildren(QLabel) if lb.isVisibleTo(page)]
    assert SETTINGS_LABEL in texts
    assert any(SETTINGS_HINT in t for t in texts), texts


def test_shortcuts_row_order_in_advanced(advanced):
    page = advanced

    def y(widget: QWidget) -> int:
        return widget.mapTo(page, QPoint(0, 0)).y()

    assert y(page.export_row) < y(page.shortcuts_row) < y(page.version_row) < y(page.license_row)


def test_s18_tab_order_export_table_notices(with_notices, qtbot):
    page = _settings_page(qtbot)
    assert page.notices_button.isVisibleTo(page)
    table = page.shortcuts_table
    page.export_button.setFocus(Qt.FocusReason.TabFocusReason)
    settle()
    QTest.keyClick(page.export_button, Qt.Key.Key_Tab)
    settle()
    assert QApplication.focusWidget() is table
    QTest.keyClick(table, Qt.Key.Key_Tab)
    settle()
    assert QApplication.focusWidget() is page.notices_button, "S17b: Tab từ bảng ra nút kế, không đi qua ô"
    QTest.keyClick(page.notices_button, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    settle()
    assert QApplication.focusWidget() is table
    QTest.keyClick(table, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    settle()
    assert QApplication.focusWidget() is page.export_button, "S17b: Shift+Tab về export_button"


def test_s17b_tab_leaves_table_without_notices(qtbot, monkeypatch, tmp_path):
    exe = tmp_path / "Teleport.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(exe))
    page = _settings_page(qtbot)
    assert not page.notices_button.isVisibleTo(page)
    table = page.shortcuts_table
    table.setFocus(Qt.FocusReason.TabFocusReason)
    settle()
    assert QApplication.focusWidget() is table
    QTest.keyClick(table, Qt.Key.Key_Tab)
    settle()
    focus = QApplication.focusWidget()
    assert focus is not table and not table.isAncestorOf(focus), "Tab không kẹt trong bảng"
    assert focus is not page.export_button


def test_s19_language_change_rebuilds_table_keeps_row(advanced, qapp):
    from teleport.ui import i18n, shortcuts

    table = advanced.shortcuts_table
    table.setCurrentCell(5, 0)
    settle()
    assert table.currentRow() == 5
    vi_rows = [table.item(r, 0).text() for r in range(table.rowCount())]
    i18n.set_language("en")
    settle()
    assert i18n.current_language() == "en"
    table = advanced.shortcuts_table
    assert table.rowCount() == 12
    en_rows = [(table.item(r, 0).text(), table.item(r, 1).text()) for r in range(12)]
    assert en_rows == shortcuts.table_rows()
    assert [d for d, _ in en_rows] != vi_rows
    assert table.currentRow() == 5, "giữ hàng hiện hành"
    assert [table.horizontalHeaderItem(c).text() for c in range(2)] != list(COLUMNS)
    assert table.accessibleName() != SETTINGS_LABEL
    for r in range(12):
        d, k = en_rows[r]
        assert table.item(r, 0).data(Qt.ItemDataRole.AccessibleTextRole) == f"{d}: {k}"
    for bar in (table.verticalScrollBar(), table.horizontalScrollBar()):
        assert bar.maximum() == 0, "H7: tính lại chiều cao sau retranslate()"


def test_h7_table_fits_narrow_english_window(qtbot, qapp):
    """H7: ở 720×460, English, bảng không có gì để cuộn (cột 0 xuống dòng thay vì tràn)."""
    from teleport.ui import i18n

    i18n.set_language("en")
    settle()
    page = _settings_page(qtbot, size=(720, 460))
    table = page.shortcuts_table
    settle(qtbot, 30)
    for bar in (table.verticalScrollBar(), table.horizontalScrollBar()):
        assert bar.maximum() == 0
    assert table.horizontalHeader().length() <= table.viewport().width()
