"""Bản dịch English của giao diện (spec D6 mục 2.7, test 5.6, quyết định 12.10 và 12.13).

Viết từ spec, không từ code:

- **`.ts` khớp nguồn.** Tập khóa `(ngữ cảnh, nguồn, disambiguation)` trích từ `src/teleport/ui/**/*.py`
  bằng bộ trích `ast` **riêng của test** (không import `packaging/i18n/update.py`, để lỗi của công cụ
  không tự xác nhận chính nó) phải bằng tập khóa trong `teleport_en.ts`; cờ numerus cũng phải khớp.
  Bộ trích nhận `QCoreApplication.translate(...)` (cả `QGuiApplication`/`QApplication`) và bí danh
  `t = QCoreApplication.translate` theo phạm vi lồng nhau (thân lớp không lộ tên cho phương thức).
  Một tham chiếu `….translate` mà không phải lời gọi hay phép gán bí danh (ví dụ truyền làm callback)
  là chỗ không trích tĩnh được: báo lỗi, không bỏ qua.
- **Không dở dang:** mọi `<translation>` không có thuộc tính `type` (`unfinished`, `vanished`,
  `obsolete`), không rỗng; numerus có đúng 2 `<numerusform>` không rỗng (tiếng Anh: số ít, số nhiều).
- **Placeholder:** tập `{tên}` của bản dịch (mọi dạng numerus) bằng tập của nguồn; `%n` có trong cả hai
  dạng numerus; nguồn có `%n` khi và chỉ khi lời gọi có `n` (mục 2.4: chuỗi đếm đổi sang `%n`).
- **Nguồn sạch:** không chuỗi được dịch nào còn `{n}`/`{count}`; không còn lời gọi `.tr(` (12.10).
- **`.qm` khớp `.ts` theo nội dung (12.13):** nạp `QTranslator`, với từng câu
  `translate(ctx, src, disamb, n)` trả đúng bản dịch (numerus: n=1 → dạng 1, n=2 → dạng 2).
- **Cửa sổ và khay English:** sau `i18n.set_language("en")` (trước khi dựng, như lúc khởi động; hay
  đổi lúc đang chạy) không widget nào của `MainWindow` (bắt đầu, đang khởi động, đang chạy, lỗi khởi
  động, cuộc trò chuyện, Tìm máy mới, mọi mục Cài đặt) và `Tray` còn chữ có dấu tiếng Việt, kể cả
  widget đang ẩn, tooltip, tên/mô tả trợ năng, placeholder, mục combo, dữ liệu của danh sách. Ngoại lệ
  duy nhất: tên tự gọi “Tiếng Việt” (mục 2.7 không dịch tên tự gọi). Dữ liệu của test (tên máy, đường
  dẫn) chỉ dùng chữ ASCII nên không cần ngoại lệ.
- **Không tràn chữ ở 720×460 (English):** cửa sổ giữ đúng 720×460 (không bị nội dung đẩy rộng ra),
  không vùng cuộn nào đang hiện có thanh cuộn ngang, và mọi nút/nhãn một dòng (`QLabel` đúng lớp, không
  xuống dòng) đang hiện có `sizeHint().width() ≤ width()` (chữ không bị cắt). Đo bằng bố cục Qt (không
  đo pixel ảnh) nên vững trên `offscreen`.
- `available_languages()` có `"en"`; `i18n.loadable("en")`; locale hệ điều hành `en_GB`/`en_US` → `en`;
  đổi vi → en → vi lúc chạy: chữ trên cửa sổ đổi rồi trở lại đúng như cũ.
- `ui.app._assets_ok()` bắt `.qm` hỏng: gói `teleport.ui` (bản chép trong `tmp_path`, giả qua
  `importlib.resources.files`) có `i18n/teleport_en.qm` là rác → False; bản chép nguyên vẹn → True
  (đối chứng: đỏ là do `.qm`, không do font hay icon).

Giả định: `.ts`/`.qm` nằm ở `<gói teleport.ui>/i18n/teleport_en.{ts,qm}` (mục 2.4); đường dẫn lấy từ
`importlib.util.find_spec("teleport.ui")`, tức đúng cây mã đang được test. Widget tự vẽ chữ trong
`paintEvent` mà không đặt `accessibleName` thì test không đọc được chữ đó (giới hạn đã biết).
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

# Chữ cái có dấu của tiếng Việt (như `tests/ui/test_i18n_theme.py`).
VIETNAMESE = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.IGNORECASE
)
PLACEHOLDER = re.compile(r"\{(\w+)\}")  # như `texts.fill`
ALLOWED_VIETNAMESE = {"Tiếng Việt"}  # tên tự gọi của ngôn ngữ nguồn: không dịch (mục 2.7)
# Từ tiếng Anh có dấu trùng chữ cái tiếng Việt (“café”): bỏ trước khi tìm chữ Việt.
ENGLISH_ACCENTED = re.compile(r"\bcaf[ée]s?\b", re.IGNORECASE)
WIDTH, HEIGHT = 720, 460
RECEIVE_DIR = Path("C:/Users/Minh/Downloads/Teleport")
NUMERUS_FORMS = 2

Key = tuple[str, str, str]  # (ngữ cảnh, nguồn, disambiguation; "" = không có)


# =================================================================================================
# Đường dẫn
# =================================================================================================


def _ui_dir() -> Path:
    spec = importlib.util.find_spec("teleport.ui")
    assert spec is not None and spec.origin is not None
    return Path(spec.origin).resolve().parent


def _ts_path() -> Path:
    return _ui_dir() / "i18n" / "teleport_en.ts"


def _qm_path() -> Path:
    return _ui_dir() / "i18n" / "teleport_en.qm"


# =================================================================================================
# Bộ trích `ast` riêng của test
# =================================================================================================

_OWNERS = {"QCoreApplication", "QGuiApplication", "QApplication"}
_ARG_NAMES = (("context",), ("key", "sourceText"), ("disambiguation",), ("n",))
_SCOPE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _is_translate_attr(node: ast.AST) -> bool:
    if not isinstance(node, ast.Attribute) or node.attr != "translate":
        return False
    owner = node.value
    if isinstance(owner, ast.Name):
        return owner.id in _OWNERS
    return isinstance(owner, ast.Attribute) and owner.attr in _OWNERS


def _literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _scope_nodes(scope: ast.AST):
    """Nút thuộc riêng phạm vi `scope` (gặp hàm/lớp/lambda lồng thì trả nút đó, không đi vào trong)."""
    todo = list(ast.iter_child_nodes(scope))
    while todo:
        node = todo.pop()
        yield node
        if not isinstance(node, _SCOPE_TYPES):
            todo.extend(ast.iter_child_nodes(node))


@dataclass
class Extracted:
    messages: dict[Key, bool] = field(default_factory=dict)  # khóa → numerus
    locations: dict[Key, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    tr_calls: list[str] = field(default_factory=list)


Stack = list[tuple[ast.AST, set[str]]]


class _Visitor:
    def __init__(self, where: str, out: Extracted) -> None:
        self.where = where
        self.out = out
        self.handled: set[int] = set()  # id các nút `….translate` đã hiểu (gọi trực tiếp hoặc gán bí danh)

    @staticmethod
    def _visible(name: str, stack: Stack) -> bool:
        for i, (node, aliases) in enumerate(reversed(stack)):
            if i > 0 and isinstance(node, ast.ClassDef):
                continue  # thân lớp không lộ tên cho phạm vi lồng trong nó
            if name in aliases:
                return True
        return False

    def _aliases(self, scope: ast.AST, stack: Stack) -> set[str]:
        aliases: set[str] = set()
        for node in _scope_nodes(scope):
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None or not all(isinstance(t, ast.Name) for t in targets):
                continue
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            if _is_translate_attr(value):
                self.handled.add(id(value))
                aliases |= names
            elif isinstance(value, ast.Name) and (
                value.id in aliases or self._visible(value.id, [*stack, (scope, aliases)])
            ):
                aliases |= names
        return aliases

    def visit_scope(self, scope: ast.AST, stack: Stack) -> None:
        stack = [*stack, (scope, self._aliases(scope, stack))]
        for node in _scope_nodes(scope):
            if isinstance(node, _SCOPE_TYPES):
                self.visit_scope(node, stack)
            elif isinstance(node, ast.Call):
                self._call(node, stack)

    def _call(self, call: ast.Call, stack: Stack) -> None:
        where = f"{self.where}:{call.lineno}"
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr == "tr":
            self.out.tr_calls.append(where)
            return
        if _is_translate_attr(func):
            self.handled.add(id(func))
        elif not (isinstance(func, ast.Name) and self._visible(func.id, stack)):
            return
        if len(call.args) > 4 or any(isinstance(a, ast.Starred) for a in call.args):
            self.out.errors.append(f"{where}: đối số không trích được")
            return
        args: list[ast.expr | None] = [None] * 4
        for i, arg in enumerate(call.args):
            args[i] = arg
        for kw in call.keywords:
            index = next((i for i, names in enumerate(_ARG_NAMES) if kw.arg in names), None)
            if index is None:
                self.out.errors.append(f"{where}: đối số lạ {kw.arg}")
                return
            args[index] = kw.value
        context, source = _literal(args[0]), _literal(args[1])
        if context is None or source is None:
            self.out.errors.append(f"{where}: ngữ cảnh/nguồn không phải literal")
            return
        comment = ""
        comment_node = args[2]
        if comment_node is not None and not (
            isinstance(comment_node, ast.Constant) and comment_node.value is None
        ):
            literal = _literal(comment_node)
            if literal is None:
                self.out.errors.append(f"{where}: disambiguation không phải literal")
                return
            comment = literal
        key = (context, source, comment)
        numerus = args[3] is not None
        old = self.out.messages.get(key)
        if old is not None and old != numerus:
            self.out.errors.append(f"{where}: {source!r} vừa có vừa không có n")
        self.out.messages[key] = numerus
        self.out.locations.setdefault(key, []).append(where)


def extract_ui_sources() -> Extracted:
    root = _ui_dir()
    out = Extracted()
    for path in sorted(root.rglob("*.py")):
        where = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_bytes(), filename=str(path))
        visitor = _Visitor(where, out)
        visitor.visit_scope(tree, [])
        for node in ast.walk(tree):
            if _is_translate_attr(node) and id(node) not in visitor.handled:
                out.errors.append(f"{where}:{node.lineno}: dùng translate theo cách không trích tĩnh được")
    return out


@pytest.fixture(scope="module")
def extracted() -> Extracted:
    return extract_ui_sources()


# =================================================================================================
# Đọc .ts
# =================================================================================================


@dataclass
class TsMessage:
    key: Key
    numerus: bool
    kind: str | None  # thuộc tính `type` của <translation> (None = đã dịch xong)
    text: str  # bản dịch (không numerus)
    forms: list[str]  # các <numerusform>
    has_translation: bool


def read_ts() -> tuple[ET.Element, list[TsMessage]]:
    path = _ts_path()
    if not path.is_file():
        pytest.fail(f"chưa có {path} (chờ code: sinh bằng packaging/i18n/update.py)")
    root = ET.parse(path).getroot()
    out: list[TsMessage] = []
    for context in root.iter("context"):
        name = context.findtext("name") or ""
        for message in context.iter("message"):
            translation = message.find("translation")
            forms = (
                [f.text or "" for f in translation.findall("numerusform")] if translation is not None else []
            )
            out.append(
                TsMessage(
                    key=(name, message.findtext("source") or "", message.findtext("comment") or ""),
                    numerus=message.get("numerus") == "yes",
                    kind=translation.get("type") if translation is not None else None,
                    text=(translation.text or "") if translation is not None else "",
                    forms=forms,
                    has_translation=translation is not None,
                )
            )
    return root, out


@pytest.fixture(scope="module")
def ts() -> list[TsMessage]:
    return read_ts()[1]


def _has_vietnamese(text: str) -> bool:
    return VIETNAMESE.search(ENGLISH_ACCENTED.sub("", text)) is not None


def _translations(m: TsMessage) -> list[str]:
    return m.forms if m.numerus else [m.text]


# =================================================================================================
# Bộ trích của test: tự kiểm
# =================================================================================================


def test_test_extractor_finds_known_strings(extracted):
    """Bộ trích của test thấy lời gọi trực tiếp, qua bí danh `t`, ở `Theme` (12.7) và `Tray` (12.10)."""
    keys = set(extracted.messages)
    assert ("Theme", "Bạc hà", "") in keys
    assert ("Texts", "Hãy dừng nó rồi bấm Thử lại.", "") in keys  # qua `t = QCoreApplication.translate`
    assert ("Tray", "Menu của Teleport", "") in keys
    assert len(keys) > 200, len(keys)


def test_test_extractor_alias_scoping():
    """Bí danh ở hàm bao ngoài, closure, lambda được nhận; bí danh trong thân lớp không lộ cho phương thức."""
    code = (
        "from PySide6.QtCore import QCoreApplication\n"
        "def outer():\n"
        "    t = QCoreApplication.translate\n"
        "    def inner():\n"
        "        return t('A', 'trong closure')\n"
        "    f = lambda: t('A', 'trong lambda', None, 3)\n"
        "    return inner, f\n"
        "class K:\n"
        "    t = QCoreApplication.translate\n"
        "    def m(self):\n"
        "        return t('A', 'không phải dịch')\n"
    )
    out = Extracted()
    _Visitor("x.py", out).visit_scope(ast.parse(code), [])
    assert out.messages == {("A", "trong closure", ""): False, ("A", "trong lambda", ""): True}


# =================================================================================================
# Nguồn sạch
# =================================================================================================


def test_ui_sources_have_no_tr_calls(extracted):
    """12.10: `.tr(` không trích tĩnh được; đợt 3 đổi hết sang `QCoreApplication.translate`."""
    assert extracted.tr_calls == []


def test_ui_translate_calls_are_all_extractable(extracted):
    """Mọi lời gọi dịch có ngữ cảnh/nguồn/disambiguation literal; không dùng `translate` kiểu lạ."""
    assert extracted.errors == []


def test_no_count_placeholder_left_in_translated_sources(extracted):
    """Mục 2.4: chuỗi đếm `{n}`/`{count}` đổi sang numerus `%n` (Q6)."""
    bad = [
        (key, extracted.locations[key])
        for key in extracted.messages
        if {"n", "count"} & set(PLACEHOLDER.findall(key[1]))
    ]
    assert bad == []


def test_percent_n_only_in_numerus_calls(extracted):
    """Nguồn có `%n` thì lời gọi phải truyền `n` (nếu không Qt để nguyên “%n”), và ngược lại."""
    bad = [
        (key, numerus, extracted.locations[key])
        for key, numerus in extracted.messages.items()
        if ("%n" in key[1]) != numerus
    ]
    assert bad == []


# =================================================================================================
# .ts
# =================================================================================================


def test_ts_header_is_ts21_english_from_vietnamese():
    root, _ = read_ts()
    assert root.tag == "TS"
    assert (root.get("version"), root.get("language"), root.get("sourcelanguage")) == ("2.1", "en", "vi")


def test_ts_keys_match_sources(extracted, ts):
    in_ts = [m.key for m in ts]
    assert len(in_ts) == len(set(in_ts)), "khóa trùng trong .ts"
    missing = sorted(set(extracted.messages) - set(in_ts))
    extra = sorted(set(in_ts) - set(extracted.messages))
    assert (missing, extra) == ([], []), "(thiếu trong .ts, thừa trong .ts): chạy lại update.py"


def test_ts_numerus_flag_matches_sources(extracted, ts):
    bad = [m.key for m in ts if m.key in extracted.messages and extracted.messages[m.key] != m.numerus]
    assert bad == []


def test_ts_has_no_unfinished_empty_vanished_or_obsolete(ts):
    bad = []
    for m in ts:
        if not m.has_translation:
            bad.append((m.key, "không có <translation>"))
        elif m.kind is not None:
            bad.append((m.key, f'type="{m.kind}"'))
        elif m.numerus:
            if len(m.forms) != NUMERUS_FORMS or not all(f.strip() for f in m.forms):
                bad.append((m.key, f"numerus {m.forms!r}"))
        elif not m.text.strip():
            bad.append((m.key, "rỗng"))
    assert bad == []


def test_ts_placeholders_preserved(ts):
    bad = []
    for m in ts:
        wanted = set(PLACEHOLDER.findall(m.key[1]))
        bad += [(m.key, text) for text in _translations(m) if set(PLACEHOLDER.findall(text)) != wanted]
    assert bad == []


def test_ts_numerus_forms_keep_percent_n(ts):
    numerus = [m for m in ts if m.numerus]
    assert numerus, "đợt 3 phải có chuỗi đếm %n (mục 2.4)"
    bad = [(m.key, m.forms) for m in numerus if "%n" not in m.key[1] or not all("%n" in f for f in m.forms)]
    assert bad == []


def test_ts_translations_have_no_vietnamese_letters(ts):
    bad = [(m.key, t) for m in ts for t in _translations(m) if _has_vietnamese(t)]
    assert bad == []


# =================================================================================================
# .qm
# =================================================================================================


def test_qm_matches_ts(qapp, ts):
    """12.13: so theo nội dung, không so byte."""
    from PySide6.QtCore import QTranslator

    path = _qm_path()
    assert path.is_file(), f"chưa có {path} (chờ code)"
    translator = QTranslator()
    assert translator.load(str(path))
    bad = []
    for m in ts:
        ctx, src, comment = m.key
        disamb = comment or None
        if m.numerus:
            got = [translator.translate(ctx, src, disamb, 1), translator.translate(ctx, src, disamb, 2)]
            if got != m.forms:
                bad.append((m.key, m.forms, got))
        else:
            one = translator.translate(ctx, src, disamb)
            if one != m.text:
                bad.append((m.key, m.text, one))
    assert bad == []
    assert translator.translate("KhongCo", "câu không có trong bản dịch") == ""


# =================================================================================================
# i18n: ngôn ngữ có sẵn, locale, nạp được
# =================================================================================================


@pytest.fixture
def back_to_source(qapp):
    """Test đổi ngôn ngữ: trả về chuỗi nguồn sau test (trạng thái cấp module của `i18n`)."""
    from teleport.ui import i18n

    yield i18n
    i18n.set_language(i18n.SOURCE_LANGUAGE)
    qapp.processEvents()


def test_available_languages_include_en(back_to_source):
    assert "en" in back_to_source.available_languages()


def test_en_qm_is_loadable(back_to_source):
    assert back_to_source.loadable("en")


@pytest.mark.parametrize("locale", ["en_GB", "en_US", "en"])
def test_english_system_locale_installs_en(back_to_source, monkeypatch, qapp, locale):
    """Q7: một `teleport_en` cho mọi `en_*`."""
    from PySide6.QtCore import QCoreApplication

    i18n = back_to_source
    monkeypatch.setattr(i18n, "system_language", lambda: locale)
    i18n.install(qapp, None)
    assert i18n.current_language() == "en"
    english = QCoreApplication.translate("Tray", "Menu của Teleport")
    assert english != "Menu của Teleport" and not VIETNAMESE.search(english)


def test_numerus_strings_render_count_in_english(qapp, back_to_source, ts):
    """Lúc chạy: `QCoreApplication.translate(..., n)` chọn đúng dạng số ít/số nhiều và thay `%n`."""
    from PySide6.QtCore import QCoreApplication

    _english(back_to_source, qapp)
    bad = []
    for m in (m for m in ts if m.numerus):
        ctx, src, comment = m.key
        for n, form in ((1, m.forms[0]), (2, m.forms[1]), (7, m.forms[1])):
            got = QCoreApplication.translate(ctx, src, comment or None, n)
            if got != form.replace("%n", str(n)):
                bad.append((m.key, n, got))
    assert bad == []


# =================================================================================================
# Cửa sổ và khay bằng English
# =================================================================================================


def _device(name: str, *, paired: bool, online: bool = True, connected: bool = False, os_name="windows"):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=hashlib.sha256(name.encode()).hexdigest()[:32],
        name=name,
        os=os_name if online else None,
        paired=paired,
        online=online,
        connected=connected,
        addresses=("192.168.1.20",) if online else (),
        port=47474 if online else None,
    )


def _window(qtbot):
    from teleport.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    return window


def _running(qtbot, views=()):
    window = _window(qtbot)
    window.devices.reset(list(views))
    window.show_running("Laptop-Minh", RECEIVE_DIR)
    window.set_addresses(["192.168.1.15"], None)
    return window


def _some_devices():
    return [
        _device("PC-Nha", paired=True, connected=True),
        _device("MacBook-Lan", paired=True, os_name="macos"),
        _device("Ubuntu-Lab", paired=True, online=False),
        _device("Laptop-Khach", paired=False),
    ]


def scene_welcome(qtbot):
    window = _window(qtbot)
    window.show_welcome("Laptop-Minh")
    return window


def scene_starting(qtbot):
    window = _window(qtbot)
    window.show_starting()
    return window


def scene_running_empty(qtbot):
    return _running(qtbot)


def scene_running_unavailable(qtbot):
    window = _window(qtbot)
    window.show_running("Laptop-Minh", None, Path("E:/Teleport"))
    window.set_addresses(["192.168.1.15"], None)
    return window


def _chat(window, views, device):
    """`ChatView` đặt vào khung phải như `TransfersController` (spec B3), đang mở luồng của `device`."""
    from teleport.ui.chat import ChatView

    view = ChatView(window.devices, window.transfers_area)
    layout = window.transfers_area.layout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(view)
    view.content_changed.connect(lambda: window.set_transfer_summary(view.has_content(), view.active_count()))
    window.conversations.current_changed.connect(view.set_device)
    view.set_device_names({v.device_id: v.name for v in views})
    view.set_receive_dir(RECEIVE_DIR)
    view.history_needed.connect(lambda device_id: view.load_history(device_id, []))
    assert window.open_conversation(device.device_id)
    view.set_device(device.device_id)
    return view


def _transfer(device_id: str, direction: str, i: int, status: str, name: str, size: int, done: int = 0):
    from teleport.core.messages import FileEntry
    from teleport.core.transfer import Direction, TransferInfo, TransferKey, TransferStatus

    return TransferInfo(
        key=TransferKey(device_id, Direction(direction), f"{i:032x}"),
        status=TransferStatus(status),
        files=(FileEntry(name, size, 1_700_000_000_000),),
        names=(name,),
        file_index=0,
        done_bytes=done,
        total_bytes=size,
        unsynced_bytes=0,
    )


def _finished(info, result: str):
    from teleport.app.transfers import TransferFinished, TransferResult

    return TransferFinished(
        info=info, result=TransferResult(result), by_peer=False, reason=None, file_index=0, reject=None
    )


def _history(device, i: int, direction: str, name: str, result: str, days_ago: int):
    import datetime

    from teleport.core.history import HistoryEntry
    from teleport.core.transfer import Direction

    at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days_ago)
    return HistoryEntry(
        direction=Direction(direction),
        device_id=device.device_id,
        device_name=device.name,
        transfer_id=f"{i:032x}",
        file_count=1,
        total_bytes=420 * 2**20,
        done_bytes=420 * 2**20 if result == "done" else 0,
        names=(name,),
        result=result,
        finished_at=at,
        saved_path=str(RECEIVE_DIR / name) if direction == "receive" and result == "done" else None,
    )


def scene_conversation(qtbot):
    """Luồng chat (spec B3) của máy đang chọn có đủ loại bong bóng: lịch sử (xong, lỗi, đã từ chối, hôm
    qua và một năm trước), nhận xong (“Hiện trong thư mục”), gửi lỗi có “Gửi lại”, đang gửi (tốc độ, còn …),
    đang chờ, bong bóng tạm “Đang chuẩn bị…”, dòng mốc, nút “↓ Mới” và thông báo có nút hành động."""
    from teleport.app.transfers import FileDone, TransferProgress, TransferStatusChanged
    from teleport.ui import texts

    views = _some_devices()
    window = _running(qtbot, views)
    nha = views[0]
    view = _chat(window, views, nha)
    view._history_timer.stop()
    view.history_needed.disconnect()
    view.history_needed.connect(
        lambda device_id: view.load_history(
            device_id,
            [
                _history(nha, 1, "receive", "slide.pptx", "done", 400),
                _history(nha, 2, "send", "old-movie.mkv", "rejected_user", 1),
                _history(nha, 3, "receive", "music.mp3", "disk_failed", 1),
            ],
        )
    )
    view._request_history()
    received = _transfer(
        nha.device_id, "receive", 10, "verifying", "photos.zip", 1_800 * 2**20, 1_800 * 2**20
    )
    view.handle(TransferStatusChanged(received))
    view.handle(FileDone(received.key, 0, "photos.zip", RECEIVE_DIR / "photos.zip"))
    view.handle(_finished(received, "done"))
    report = _transfer(nha.device_id, "send", 11, "transferring", "report.pdf", 4 * 2**20, 2**20)
    view.handle(TransferStatusChanged(report))
    view.handle(_finished(report, "source_changed"))
    view.set_resendable(report.key, True)
    size = 18 * 2**30
    sending = _transfer(nha.device_id, "send", 12, "transferring", "movie-4k.mkv", size, size // 2)
    view.handle(TransferStatusChanged(sending))
    view.handle(TransferProgress(sending, 94 * 2**20, 60.0, shown_bytes=sending.done_bytes, idle_seconds=0.0))
    waiting = _transfer(nha.device_id, "receive", 13, "waiting", "contract.docx", 2**20)
    view.handle(TransferStatusChanged(waiting))
    view.add_pending(nha.device_id, [Path("C:/Users/Minh/Videos/slides.pptx")])
    view._set_new_count(2)  # như khi đã cuộn lên rồi có lượt mới
    view.show_notice(texts.menu_open, texts.retry, lambda: None)  # câu dựng bằng hàm: dịch lại được
    thread = view.thread_for(nha.device_id)
    assert thread is not None and len(thread.history_bubbles()) == 3 and len(view.rows()) == 4
    return window


def scene_chat_offline(qtbot):
    """Máy đã ghép đôi đang ngoại tuyến: lượt gửi chờ kết nối, câu ngoại tuyến ở thanh dưới."""
    from teleport.app.transfers import TransferStatusChanged

    views = _some_devices()
    window = _running(qtbot, views)
    lab = views[2]
    view = _chat(window, views, lab)
    view.set_connected(lab.device_id, False)
    view.handle(TransferStatusChanged(_transfer(lab.device_id, "send", 20, "waiting", "demo.mp4", 3 * 2**30)))
    return window


def scene_chat_empty(qtbot):
    """Máy chưa có lượt nào: màn rỗng “Kéo file vào đây để gửi cho X”."""
    views = _some_devices()
    window = _running(qtbot, views)
    view = _chat(window, views, views[1])
    view._history_timer.stop()
    view._request_history()
    return window


def _error_scene(code: str):
    def build(qtbot):
        window = _window(qtbot)
        window.show_error(code, "C:/Teleport\n[WinError 5] Access is denied" if code == "config_dir" else "")
        return window

    return build


def _discover_scene(views_factory):
    def build(qtbot):
        from teleport.ui.main_window import Page

        window = _running(qtbot, views_factory())
        assert window.open_page(Page.DISCOVER)
        return window

    return build


def scene_address_entry(qtbot):
    window = _running(qtbot)
    assert window.open_address_entry()
    return window


def _settings_scene(section_name: str):
    def build(qtbot):
        from teleport.app import autostart
        from teleport.app.settings import DeviceSettings
        from teleport.ui.main_window import Page
        from teleport.ui.settings import Section, SettingsPage, SettingsSnapshot

        views = _some_devices()
        window = _running(qtbot, views)
        page = SettingsPage(window.devices, window.pages)
        window.add_page(Page.SETTINGS, page)
        page.set_values(
            SettingsSnapshot(
                name="Laptop-Minh",
                visible=section_name != "privacy",  # mục Riêng tư: máy đang ẩn
                rate_limit=20 * 1024 * 1024,
                temp_retention_days=None,
                language=None,
                autostart=True,
                devices={v.device_id: DeviceSettings(ask_before_receive=True) for v in views if v.paired},
            )
        )
        page.set_language(None, ("en", "vi"))
        page.set_autostart(autostart.AutostartState.ON)
        page.set_receive_dir(RECEIVE_DIR)
        page.set_change_available(True)
        page.set_loaded(True)
        assert window.open_page(Page.SETTINGS)
        page.show_section(Section(section_name))
        return window

    return build


SETTINGS_SECTIONS = ("general", "appearance", "privacy", "devices", "transfer", "advanced")
START_ERRORS = ("locked", "config_dir", "identity", "trust_store", "receive_dir", "port", "other")

SCENES = {
    "welcome": scene_welcome,
    "starting": scene_starting,
    "running_empty": scene_running_empty,
    "running_unavailable": scene_running_unavailable,
    "conversation": scene_conversation,
    "chat_offline": scene_chat_offline,
    "chat_empty": scene_chat_empty,
    "discover": _discover_scene(_some_devices),
    "discover_empty": _discover_scene(list),
    "discover_list": _discover_scene(lambda: [_device(f"PC-{i}", paired=False) for i in range(9)]),
    "address_entry": scene_address_entry,
    **{f"error_{code}": _error_scene(code) for code in START_ERRORS},
    **{f"settings_{name}": _settings_scene(name) for name in SETTINGS_SECTIONS},
}


def _strings(root) -> list[tuple[str, str]]:
    """(chỗ, chữ) của mọi widget trong `root`, kể cả đang ẩn: chữ, tooltip, trợ năng, placeholder, combo,
    dữ liệu của danh sách, hành động (menu)."""
    from PySide6.QtCore import QModelIndex
    from PySide6.QtWidgets import (
        QAbstractButton,
        QAbstractItemView,
        QComboBox,
        QGroupBox,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QTabWidget,
        QTextEdit,
        QWidget,
    )

    out: list[tuple[str, str]] = []

    def add(where: str, text: object) -> None:
        if isinstance(text, str) and text:
            out.append((where, text))

    roles = (
        Qt.ItemDataRole.DisplayRole,
        Qt.ItemDataRole.ToolTipRole,
        Qt.ItemDataRole.StatusTipRole,
        Qt.ItemDataRole.AccessibleTextRole,
        Qt.ItemDataRole.AccessibleDescriptionRole,
    )
    attrs = ("windowTitle", "toolTip", "statusTip", "whatsThis", "accessibleName", "accessibleDescription")
    for w in [root, *root.findChildren(QWidget)]:
        where = f"{type(w).__name__}({w.objectName()})"
        for attr in attrs:
            add(f"{where}.{attr}", getattr(w, attr)())
        if isinstance(w, QLabel | QAbstractButton):
            add(f"{where}.text", w.text())
        if isinstance(w, QLineEdit):
            add(f"{where}.text", w.text())
            add(f"{where}.placeholder", w.placeholderText())
        if isinstance(w, QTextEdit | QPlainTextEdit):
            add(f"{where}.text", w.toPlainText())
            add(f"{where}.placeholder", w.placeholderText())
        if isinstance(w, QComboBox):
            for i in range(w.count()):
                add(f"{where}.item{i}", w.itemText(i))
                add(f"{where}.item{i}.tooltip", w.itemData(i, Qt.ItemDataRole.ToolTipRole))
        if isinstance(w, QGroupBox):
            add(f"{where}.title", w.title())
        if isinstance(w, QTabWidget):
            for i in range(w.count()):
                add(f"{where}.tab{i}", w.tabText(i))
                add(f"{where}.tab{i}.tooltip", w.tabToolTip(i))
        if isinstance(w, QAbstractItemView) and w.model() is not None:
            model, top = w.model(), QModelIndex()
            try:
                columns = model.columnCount(top)
            except TypeError:  # QAbstractListModel: columnCount là private trong PySide6, luôn 1 cột
                columns = 1
            for row in range(model.rowCount(top)):
                for col in range(columns):
                    index = model.index(row, col)
                    for role in roles:
                        add(f"{where}[{row},{col}].{role.name}", model.data(index, role))
        for action in w.actions():
            add(f"{where}.action.text", action.text())
            add(f"{where}.action.toolTip", action.toolTip())
    return out


def _vietnamese(strings: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [
        (where, text) for where, text in strings if _has_vietnamese(text) and text not in ALLOWED_VIETNAMESE
    ]


def _english(i18n, qapp) -> None:
    i18n.set_language("en")
    for _ in range(3):
        qapp.processEvents()
    assert i18n.current_language() == "en", "không nạp được teleport_en.qm (chờ code)"


def _show(window, qapp, width: int = WIDTH, height: int = HEIGHT) -> None:
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.resize(width, height)
    window.show()
    for _ in range(3):  # hàng đổi bố cục theo bề ngang cần thêm lượt layout (như test_snapshots)
        qapp.processEvents()


@pytest.mark.parametrize("scene", list(SCENES))
def test_scene_shows_vietnamese_before_english(qtbot, qapp, back_to_source, scene):
    """Đối chứng cho test dưới: ở chuỗi nguồn, bộ đọc chữ của test thấy chữ Việt ở mọi cảnh (không rỗng)."""
    window = SCENES[scene](qtbot)
    _show(window, qapp)
    assert _vietnamese(_strings(window))


@pytest.mark.parametrize("when", ["before_build", "live_switch"])
@pytest.mark.parametrize("scene", list(SCENES))
def test_english_window_shows_no_vietnamese(qtbot, qapp, back_to_source, scene, when):
    """Mục 2.7: mọi chuỗi qua `translate`, kể cả tooltip và trợ năng; đổi lúc chạy cũng dịch hết."""
    i18n = back_to_source
    if when == "before_build":
        _english(i18n, qapp)
    window = SCENES[scene](qtbot)
    _show(window, qapp)
    if when == "live_switch":
        _english(i18n, qapp)
    assert _vietnamese(_strings(window)) == []


@pytest.mark.parametrize("when", ["before_build", "live_switch"])
def test_english_tray_shows_no_vietnamese(qapp, back_to_source, when):
    from teleport.ui.tray import Tray

    i18n = back_to_source
    if when == "before_build":
        _english(i18n, qapp)
    tray = Tray()
    try:
        if when == "live_switch":
            _english(i18n, qapp)
        strings = _strings(tray.menu)
        strings += [(f"action{i}.text", a.text()) for i, a in enumerate(tray.actions())]
        strings += [(f"action{i}.toolTip", a.toolTip()) for i, a in enumerate(tray.actions())]
        strings.append(("icon.toolTip", tray._icon.toolTip()))
        assert all(a.text() for a in tray.actions())
        assert _vietnamese(strings) == []
    finally:
        tray.dispose()


def test_language_combo_keeps_vietnamese_endonym_in_english(qtbot, qapp, back_to_source):
    """Ngoại lệ duy nhất của test trên: ô ngôn ngữ vẫn có “Tiếng Việt” (không dịch) khi đang English."""
    from PySide6.QtWidgets import QComboBox

    _english(back_to_source, qapp)
    window = SCENES["settings_appearance"](qtbot)
    items = [c.itemText(i) for c in window.findChildren(QComboBox) for i in range(c.count())]
    assert "Tiếng Việt" in items and "English" in items


# ---- Tràn chữ ở 720×460 ----------------------------------------------------------------------


def _overflow(window) -> list[str]:
    from PySide6.QtWidgets import QAbstractButton, QAbstractScrollArea, QLabel

    problems: list[str] = []
    if (window.width(), window.height()) != (WIDTH, HEIGHT):
        problems.append(f"cửa sổ {window.width()}x{window.height()} (nội dung đẩy cửa sổ quá cỡ)")
    for area in window.findChildren(QAbstractScrollArea):
        bar = area.horizontalScrollBar()
        if area.isVisible() and bar.maximum() > 0:
            problems.append(f"{type(area).__name__}({area.objectName()}) cuộn ngang {bar.maximum()} px")
    for button in window.findChildren(QAbstractButton):
        if button.isVisible() and button.text() and button.sizeHint().width() > button.width():
            problems.append(
                f"nút {button.text()!r} cần {button.sizeHint().width()} px, có {button.width()} px"
            )
    for label in window.findChildren(QLabel):
        if type(label) is not QLabel or not label.isVisible() or not label.text() or label.wordWrap():
            continue  # nhãn tự cắt “…” (lớp con) hay xuống dòng: không cắt chữ
        if label.sizeHint().width() > label.width() + 1:
            problems.append(f"nhãn {label.text()!r} cần {label.sizeHint().width()} px, có {label.width()} px")
    return problems


def test_overflow_check_detects_clipped_button_and_label(qtbot, qapp):
    """Đối chứng cho test dưới: nút và nhãn bị ép hẹp hơn chữ thì `_overflow` báo."""
    from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

    window = QWidget()
    qtbot.addWidget(window)
    layout = QVBoxLayout(window)
    button = QPushButton("Choose receive folder and many more words")
    button.setFixedWidth(40)
    label = QLabel("A rather long single line label that cannot fit")
    label.setFixedWidth(40)
    layout.addWidget(button)
    layout.addWidget(label)
    _show(window, qapp)
    problems = _overflow(window)
    assert any(p.startswith("nút") for p in problems), problems
    assert any(p.startswith("nhãn") for p in problems), problems


@pytest.mark.parametrize("scene", list(SCENES))
def test_english_fits_720x460(qtbot, qapp, back_to_source, scene):
    """Rủi ro mục 8: English dài hơn; ở cỡ nhỏ nhất không cuộn ngang, không cắt chữ nút/nhãn."""
    _english(back_to_source, qapp)
    window = SCENES[scene](qtbot)
    _show(window, qapp)
    assert _overflow(window) == []


# ---- Đổi lúc chạy ----------------------------------------------------------------------------


def test_switch_vi_en_vi_at_runtime_changes_and_restores_texts(qtbot, qapp, back_to_source):
    i18n = back_to_source
    window = SCENES["settings_general"](qtbot)
    _show(window, qapp, 980, 660)
    vietnamese = _strings(window)
    assert _vietnamese(vietnamese), "trước khi đổi phải đang hiện tiếng Việt"
    _english(i18n, qapp)
    english = _strings(window)
    assert english != vietnamese
    assert _vietnamese(english) == []
    i18n.set_language("vi")
    for _ in range(3):
        qapp.processEvents()
    assert i18n.current_language() == "vi"
    assert _not_elided(_strings(window)) == _not_elided(vietnamese)


def _not_elided(strings: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Bỏ chữ của nhãn tự cắt “…” (lớp tên có `Elided`): chữ đó theo bề ngang lúc vẽ, không theo bản dịch."""
    return [(w, t) for w, t in strings if not ("Elided" in w.split("(", 1)[0] and w.endswith(".text"))]


# =================================================================================================
# `_assets_ok` của `--selftest`
# =================================================================================================


@pytest.fixture
def ui_package_copy(monkeypatch, tmp_path):
    """Bản chép gói `teleport.ui` (tài sản + bản dịch) trong `tmp_path`, trả qua `resources.files`."""
    from importlib import resources

    root = tmp_path / "ui"
    shutil.copytree(_ui_dir(), root, ignore=shutil.ignore_patterns("__pycache__"))
    real_files = resources.files

    def files(package):
        if package == "teleport.ui":
            return root
        return real_files(package)

    monkeypatch.setattr(resources, "files", files)
    return root


def test_assets_ok_with_intact_translation(qapp, ui_package_copy, back_to_source):
    """Đối chứng cho test dưới: cùng bản chép, `.qm` nguyên vẹn → True."""
    from teleport.ui import app as ui_app

    assert (ui_package_copy / "i18n" / "teleport_en.qm").is_file(), "chưa có teleport_en.qm (chờ code)"
    assert "en" in back_to_source.available_languages()
    assert ui_app._assets_ok() is True


@pytest.mark.parametrize(
    "garbage",
    [b"", b"day khong phai file qm " * 8, b"\x3c\xb8\x64\x18" + b"\xff" * 64],
    ids=["empty", "text", "bad_body"],
)
def test_assets_ok_rejects_broken_qm(qapp, ui_package_copy, back_to_source, garbage):
    """2.6: `_assets_ok` nạp mọi mã ≠ vi trong `available_languages()`; `.qm` hỏng → False."""
    from teleport.ui import app as ui_app

    qm = ui_package_copy / "i18n" / "teleport_en.qm"
    qm.parent.mkdir(exist_ok=True)
    qm.write_bytes(garbage)
    i18n = back_to_source
    assert "en" in i18n.available_languages()
    assert i18n.loadable("en") is False
    assert ui_app._assets_ok() is False
