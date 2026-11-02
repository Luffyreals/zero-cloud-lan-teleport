"""Fixture cho test tầng `ui` (spec-p4-3 mục 6 và 10).

- Qt chạy `offscreen` (đặt bằng `os.environ.setdefault` ở mức module, trước khi có `QApplication`): test
  chạy được trên CI không có màn hình. Không cài PySide6 (extra `gui`) thì cả thư mục bị bỏ qua.
- Mọi test trong thư mục này được gắn marker `gui`; test mở socket gắn thêm `integration`. Chạy chúng
  riêng (`-m gui`), không chung lần chạy với test tầng khác; CI Windows chạy tuần tự: trong worker
  xdist vòng sự kiện Qt từng abort (docs/architecture.md mục 6).
- Module `teleport.ui.*` chỉ được import **bên trong** fixture/test, để `ui` đang viết dở chỉ làm đỏ các
  test dùng tới nó (giống `tests/conftest.py`).

Fixture chính:

- `fake_default_receive_dir` (tự dùng): `paths.default_receive_dir()` trỏ vào `tmp_path`, không bao giờ
  tạo thư mục trong Downloads thật.
- `config_dir(label, identity=True)`: thư mục cấu hình mới dưới `tmp_path` (có danh tính nếu cần).
- `node_hosts`: `make(options) -> NodeHost`; mọi host được `stop()` + `join()` khi test xong.
- `gui`: chạy `teleport.ui.app.main(argv)` **trong tiến trình**, điều khiển bằng một kịch bản (generator)
  chạy trong event loop Qt; ghi lại mọi `NodeHost`, `Tray`, `MainWindow` được tạo, ép node nghe
  `127.0.0.1`, cổng 0, không mDNS, thư mục nhận trong `tmp_path` (hay giữ `SAVED` với
  `keep_receive_dir=True`); chặn `os._exit` (lỗi của `main`
  không giết pytest) và khôi phục handler SIGINT.
- `peer_node`: một `Node` thật (máy gửi B) chạy event loop riêng trong một thread.
- `ui_helpers`: hàm phụ trợ (test không import được conftest).
- `aumid_registration` (tự dùng): `main` không ghi registry thật; fixture trả hàm đăng ký thật.
- `fake_select_native` (tự dùng): `ui.shell._select_native` giả, không mở Explorer thật; fixture trả
  bản ghi lời gọi (spec-f4 S6).
- `notify_immediate` (tự dùng): thông báo “Đã nhận…” không hoãn; tắt bằng marker `real_notify_delay`
  (spec-f4 S7).
- `ui_language_reset` (tự dùng): ngôn ngữ của hệ điều hành coi là tiếng Việt và mỗi test kết thúc ở
  chuỗi nguồn, để test không phụ thuộc locale của máy chạy test (có `teleport_en.qm` rồi).
- `motion_instant` (tự dùng): `ui/motion.py` ở chế độ tức thì (`_force_instant(True)`): mọi helper
  chuyển động gán ngay giá trị cuối, test không chờ hoạt ảnh (spec-g1 mục 3). Dọn:
  `_stop_all_for_tests()` (dừng mọi hoạt ảnh và `Loop`, không gọi callback) rồi `_reset_for_tests()`
  (xóa cache GNOME, tắt chế độ tức thì). Không chạm `animations_enabled()`: test cần “hệ điều hành
  tắt hiệu ứng” xin `real_motion` rồi vá lại hàm đó (như fixture `waves` của `test_discover.py`, nay
  sóng radar là một `motion.Loop`, spec G6).
- `backdrop_reset` (tự dùng): vá mặc định `ui/backdrop.py` `_high_contrast` → True và ba seam DWM →
  `E_FAIL` (nền đặc, không gọi DWM thật), sau mỗi test gọi `_reset_for_tests()` (gỡ bộ lọc native,
  xóa tập backdrop đang theo dõi; spec G7). Test giả Windows 11 bằng cách vá đè seam của module.
- `real_motion`: test xin khi cần hoạt ảnh chạy thật: tắt chế độ tức thì và vá
  `motion.animations_enabled` thành `lambda: True`. Chỉ kiểm giá trị cuối, không giá trị giữa chừng.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import asyncio
import contextlib
import dataclasses
import hashlib
import logging
import re
import signal
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

LOCAL = "127.0.0.1"
_UI_DIR = Path(__file__).resolve().parent

# Câu chữ người dùng duyệt nguyên văn (spec-p4-3 mục 5). Sau soat-code vòng 1: câu GUI không dùng
# backtick quanh tên lệnh mà dùng ngoặc “…” (backtick là quy ước của dòng lệnh/Markdown).
M2_HEAD = (
    "Teleport đang chạy ở nơi khác với thư mục cấu hình này (ví dụ lệnh “teleport receive” trong cửa sổ "
    "dòng lệnh)."
)
M2_HINT = "Hãy dừng nó rồi bấm Thử lại."
# Màn lần chạy đầu thay M3 (mvp F1, spec D1): chưa có danh tính → chờ người dùng bấm “Bắt đầu”.
WELCOME_HEAD = (
    "Gửi file lớn giữa các máy trong cùng mạng. Không qua cloud."  # câu giá trị (`firstRunTagline`)
)
WELCOME_F1 = "Tên này hiện với mọi máy trong cùng mạng, kể cả máy lạ chưa ghép đôi."  # mvp F1
START = "Bắt đầu"
M3_HEAD = "Máy này chưa được thiết lập Teleport."  # câu M3 cũ: không còn được hiện
QUITTING = "Teleport đang tắt hoặc chưa phản hồi."  # `acquire` hết hạn (soat-code vòng 1, (c))
M4 = "Teleport vẫn chạy ở khay hệ thống và vẫn nhận file. Chọn Thoát trong menu khay để tắt hẳn."
M5 = ("Mở Teleport", "Gửi file…", "Tạm dừng nhận", "Thoát")
M6_ACCEPT = "Nhận"
M6_REJECT = "Từ chối"
RETRY = "Thử lại"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        try:
            Path(str(item.path)).resolve().relative_to(_UI_DIR)
        except ValueError:
            continue
        item.add_marker("gui")


# =================================================================================================
# Hàm phụ trợ
# =================================================================================================


def plain(text: str) -> str:
    """Chữ trên nút/menu bỏ dấu tắt `&`."""
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def widget_texts(root) -> list[str]:
    """Mọi chữ hiện trên `root` và con của nó: tiêu đề, nhãn, nút, menu (chỉ widget đang hiện)."""
    from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QTextEdit

    out: list[str] = []
    if root.windowTitle():
        out.append(root.windowTitle())
    if isinstance(root, QMessageBox):
        out += [t for t in (root.text(), root.informativeText(), root.detailedText()) if t]
    for w in root.findChildren(QLabel):
        if w.isVisibleTo(root) and w.text():
            out.append(w.text())
    for w in root.findChildren(QAbstractButton):
        if w.isVisibleTo(root) and w.text():
            out.append(plain(w.text()))
    for w in root.findChildren(QLineEdit):
        if w.isVisibleTo(root) and w.text():
            out.append(w.text())
    for cls in (QTextEdit, QPlainTextEdit):
        for w in root.findChildren(cls):
            if w.isVisibleTo(root) and w.toPlainText():
                out.append(w.toPlainText())
    return out


def strip_markup(text: str) -> str:
    """Bỏ thẻ HTML đơn giản và gộp khoảng trắng (nhãn rich text vẫn so được với câu nguyên văn)."""
    import html

    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\s+", " ", text).strip()


def all_text(root) -> str:
    return "\n".join(strip_markup(t) for t in widget_texts(root))


def buttons_with_text(root, text: str) -> list:
    from PySide6.QtWidgets import QAbstractButton

    return [b for b in root.findChildren(QAbstractButton) if plain(b.text()) == text and b.isVisibleTo(root)]


def is_alive(obj) -> bool:
    """Đối tượng Qt còn sống (C++ chưa bị xóa)."""
    try:
        import shiboken6

        return shiboken6.isValid(obj)
    except ImportError:  # pragma: no cover
        try:
            obj.objectName()
        except RuntimeError:
            return False
        return True


def visible_message_boxes() -> list:
    from PySide6.QtWidgets import QApplication, QMessageBox

    return [w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()]


def lock_is_free(directory: Path, name: str = "node.lock") -> bool:
    from teleport.lock import NodeLock, NodeLockedError

    lock = NodeLock(directory, name)
    try:
        lock.acquire()
    except NodeLockedError:
        return False
    lock.release()
    return True


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def ui_helpers():
    return SimpleNamespace(
        LOCAL=LOCAL,
        M2_HEAD=M2_HEAD,
        M2_HINT=M2_HINT,
        WELCOME_HEAD=WELCOME_HEAD,
        WELCOME_F1=WELCOME_F1,
        START=START,
        M3_HEAD=M3_HEAD,
        QUITTING=QUITTING,
        M4=M4,
        M5=M5,
        M6_ACCEPT=M6_ACCEPT,
        M6_REJECT=M6_REJECT,
        RETRY=RETRY,
        plain=plain,
        widget_texts=widget_texts,
        strip_markup=strip_markup,
        all_text=all_text,
        buttons_with_text=buttons_with_text,
        is_alive=is_alive,
        visible_message_boxes=visible_message_boxes,
        lock_is_free=lock_is_free,
        sha256_file=sha256_file,
    )


# =================================================================================================
# Thư mục cấu hình, NodeHost
# =================================================================================================


@pytest.fixture(autouse=True)
def release_stuck_mouse_buttons(qapp):
    """Mọi test ui bắt đầu với chuột đã nhả.

    `QTest.mouseDClick` (Qt 6) không gửi lần nhả cuối, nên `QApplication.mouseButtons()` còn báo nút
    trái đang giữ sang test sau, và code xét “tiêu điểm đến từ cú bấm chuột” (`MainWindow`, cuộn cột
    trái) hiểu sai. Nhả từng nút còn giữ trên một cửa sổ tạm trước khi test chạy.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget

    held = QApplication.mouseButtons()
    if held != Qt.MouseButton.NoButton:
        sink = QWidget()
        sink.show()
        for button in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            if held & button:
                QTest.mouseRelease(sink, button)
        sink.close()
        sink.deleteLater()
    yield


@pytest.fixture(autouse=True)
def aumid_registration(monkeypatch):
    """Mọi test ui: `main` không ghi HKCU thật (`ui.app._register_app_user_model_id` thành no-op).

    Trả hàm thật cho test của chính nó (`test_app_identity.py`), test đó thay `winreg` bằng bản giả.
    """
    from teleport.ui import app

    real = app._register_app_user_model_id
    monkeypatch.setattr(app, "_register_app_user_model_id", lambda config_dir: None)
    return real


class NativeSelectSpy:
    """Bản giả của `ui.shell._select_native`: ghi `(target, picks)` mỗi lần gọi.

    `result` (mặc định False → `show_in_folder` về `open_url` mà test đã vá) là giá trị trả; `error`
    khác None thì ném lỗi đó thay vì trả.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[Path, tuple[Path, ...]]] = []
        self.result = False
        self.error: BaseException | None = None

    def __call__(self, target, picks) -> bool:
        self.calls.append((target, tuple(picks)))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def fake_select_native(monkeypatch) -> NativeSelectSpy:
    """Mọi test ui: không bao giờ mở Explorer thật (spec-f4 S6, như `aumid_registration`).

    `ui.shell._select_native` thành `NativeSelectSpy` (mặc định trả False: luồng về `open_url`). Test cần
    kiểm lời gọi native xin fixture này để đọc `calls`, hay đặt `result = True` / `error`.
    """
    from teleport.ui import shell

    spy = NativeSelectSpy()
    monkeypatch.setattr(shell, "_select_native", spy)
    return spy


@pytest.fixture(autouse=True)
def notify_immediate(request, monkeypatch) -> None:
    """Mọi test ui: thông báo “Đã nhận…” không hoãn (`NOTIFY_QUIET = NOTIFY_MAX_WAIT = 0`, spec-f4 S7),
    nên `TransfersController` flush đồng bộ ngay khi lượt nhận xong, như trước khi có gộp.

    Test gộp thật gắn `@pytest.mark.real_notify_delay` (hằng thật, hay tự vá).
    """
    if request.node.get_closest_marker("real_notify_delay") is not None:
        return
    from teleport.ui import notify

    monkeypatch.setattr(notify, "NOTIFY_QUIET", 0)
    monkeypatch.setattr(notify, "NOTIFY_MAX_WAIT", 0)


@pytest.fixture(autouse=True)
def qt_thread_gc(qapp):
    """Mọi test ui: GC vòng tham chiếu chỉ chạy trên thread Qt (`teleport.ui.gcguard`), như `main`.

    Nhiều test tự dựng `NodeHost`, peer, proxy… không qua `main`; không có guard thì GC ở các thread
    đó có thể hủy widget/QTimer ngoài thread Qt (segfault trên CI macOS). Teardown: `stop()` thu gom
    một lần trên thread chính rồi khôi phục trạng thái GC. Fixture autouse dựng trước fixture thường
    của test nên được dọn sau cùng (sau khi host, peer đã dừng).
    """
    from teleport.ui.gcguard import GcGuard

    guard = GcGuard()
    guard.start()
    yield guard
    guard.stop()


@pytest.fixture(autouse=True)
def ui_language_reset(qapp, monkeypatch):
    """Mọi test ui: `i18n.system_language()` → `vi`, và sau test về lại chuỗi nguồn (spec-d6 đợt 3).

    Có `teleport_en.qm` thì máy chạy test để locale English (CI, máy dev) làm `install(app)` /
    `apply_preference(None)` hiện English, và các test so câu tiếng Việt đỏ theo máy. Test cần ngôn ngữ
    hệ điều hành khác tự vá lại `system_language` (lần vá sau thắng). Sau test: ngôn ngữ đang dùng khác
    `vi` thì `set_language("vi")` (gỡ translator, widget còn sống nhận `LanguageChange`).
    """
    try:
        from teleport.ui import i18n
    except Exception:  # module đang hỏng: test của nó tự đỏ, không làm đỏ mọi test ui
        yield
        return
    monkeypatch.setattr(i18n, "system_language", lambda: i18n.SOURCE_LANGUAGE)
    yield
    if i18n.current_language() != i18n.SOURCE_LANGUAGE:
        i18n.set_language(i18n.SOURCE_LANGUAGE)
        qapp.processEvents()


@pytest.fixture(autouse=True)
def motion_instant(qapp):
    """Mọi test ui: chuyển động ở chế độ tức thì (spec-g1 mục 3, mục 9 Q9).

    Teardown: `_stop_all_for_tests()` (dừng hoạt ảnh/`Loop` còn chạy, không gọi `on_finished`/`on_stop`,
    trả `windowOpacity` về 1.0) rồi `_reset_for_tests()`. `motion` chưa có các seam này hay import lỗi
    (code đang viết dở) thì bỏ qua: test của chính nó tự đỏ, không làm đỏ mọi test ui.
    """
    try:
        from teleport.ui import motion

        force = motion._force_instant
        stop_all = motion._stop_all_for_tests
        reset = motion._reset_for_tests
    except Exception:
        yield
        return
    force(True)
    yield
    stop_all()
    reset()


@pytest.fixture(autouse=True)
def backdrop_reset(qapp, monkeypatch):
    """Mọi test ui: không gọi DWM thật và bộ theo dõi cài đặt của `ui/backdrop.py` không rò sang test
    sau (spec G7 mục 9 ý 10).

    Mặc định vá `_high_contrast` thành True (nền đặc, không gọi DWM) và ba seam DWM thành `E_FAIL`, nên
    cả khi chạy với `QT_QPA_PLATFORM=windows` (ảnh duyệt) cửa sổ vẫn nền đặc như ảnh của người dùng
    trước G7; test cần Mica tự vá đè. Teardown: `backdrop._reset_for_tests()` (gỡ bộ lọc native khỏi
    `qapp`, xóa tập backdrop đang theo dõi). Module chưa có seam hay import lỗi thì bỏ qua: test của
    chính nó tự đỏ.
    """
    try:
        from teleport.ui import backdrop
    except Exception:
        yield
        return
    monkeypatch.setattr(backdrop, "_high_contrast", lambda: True)
    for name in ("_dwm_extend_frame", "_dwm_set_backdrop", "_dwm_set_dark"):
        monkeypatch.setattr(backdrop, name, lambda *_args: backdrop.E_FAIL)
    yield
    backdrop._reset_for_tests()


@pytest.fixture
def real_motion(monkeypatch):
    """Hoạt ảnh của `ui/motion.py` chạy thật: tắt chế độ tức thì, `animations_enabled` → True.

    Fixture `motion_instant` (autouse, dựng trước) dọn sau cùng. Test muốn “hệ điều hành tắt hiệu ứng”
    thì vá lại `motion.animations_enabled` (lần vá sau thắng).
    """
    from teleport.ui import motion

    motion._force_instant(False)
    monkeypatch.setattr(motion, "animations_enabled", lambda: True)
    return motion


@pytest.fixture(autouse=True)
def theme_state_reset(qapp):
    """Mọi test ui: lựa chọn chế độ màu/màu nhấn của `ui/theme.py` không rò sang test sau (spec-d6 mục
    12 ý 5).

    Chụp palette + stylesheet của `qapp` trước test. Sau test: đặt lại `_mode`/`_accent` bằng
    `theme._reset_for_tests()` (về SYSTEM + màu nhấn mặc định), gọi `unsetColorScheme()` (bỏ ép sáng/tối
    của `set_preference`), rồi khôi phục palette + stylesheet (chỉ khi khác, để không polish lại mọi
    widget vô ích). Không gọi `set_preference` lúc dọn. Autouse nên dọn sau các fixture thường
    (`ui_theme`, `themed`, `restore_palette`, `monkeypatch`), tức sau khi bản vá `QStyleHints` đã gỡ.
    `theme` chưa có `_reset_for_tests` (code đang viết dở) thì bỏ bước đó; test
    `test_autouse_reset_restores_system_and_default` sẽ đỏ thay vì mọi test ui.
    """
    from PySide6.QtGui import QPalette

    old_palette = QPalette(qapp.palette())
    old_css = qapp.styleSheet()
    yield
    try:
        from teleport.ui import theme
    except Exception:  # module đang hỏng: test của nó tự đỏ, không làm đỏ teardown mọi test ui
        theme = None
    reset = getattr(theme, "_reset_for_tests", None)
    if reset is not None:
        reset()
    hints = qapp.styleHints()
    if hasattr(hints, "unsetColorScheme"):
        hints.unsetColorScheme()
    qapp.processEvents()
    if qapp.styleSheet() != old_css:
        qapp.setStyleSheet(old_css)
    if qapp.palette() != old_palette:
        qapp.setPalette(old_palette)


@pytest.fixture(autouse=True)
def fake_default_receive_dir(monkeypatch, tmp_path) -> Path:
    """Mọi test ui: `paths.default_receive_dir()` → `tmp_path / "nhan-mac-dinh"` (spec-b1b mục 11.3).

    Giao diện mặc định dùng thư mục nhận đã lưu (`ReceiveDirChoice.SAVED`); chưa lưu gì thì node mở
    `paths.default_receive_dir()`. Không vá thì test tạo thư mục thật trong Downloads của máy chạy test.
    Fixture `gui` vá lại lần nữa (thư mục `nhan-gui`); lần vá sau thắng. Trả đường dẫn đã vá.
    """
    from teleport import paths

    default = tmp_path / "nhan-mac-dinh"
    monkeypatch.setattr(paths, "default_receive_dir", lambda: default)
    return default


@pytest.fixture
def config_dir(tmp_path):
    """`config_dir(label="A", identity=True) -> Path`: thư mục cấu hình mới dưới `tmp_path`."""

    def make(label: str = "A", *, identity: bool = True) -> Path:
        from teleport.trust.identity import load_or_create_identity

        d = tmp_path / label
        d.mkdir(parents=True, exist_ok=True)
        if identity:
            load_or_create_identity(d)
        return d

    return make


@pytest.fixture
def node_options(tmp_path):
    """`node_options(config_dir, **kw) -> NodeOptions` của test: 127.0.0.1, cổng 0, không mDNS."""

    def make(config: Path, **kw) -> object:
        from teleport.ui.bridge import NodeOptions

        values = {
            "config_dir": config,
            "receive_dir": tmp_path / f"nhan-{config.name}",
            "mdns": None,
            "host": LOCAL,
            "port": 0,
        }
        values.update(kw)
        return NodeOptions(**values)

    return make


@pytest.fixture
def node_hosts(qtbot):
    """`make(options) -> NodeHost`. Khi test xong: `stop()` rồi `join(…)` mọi host (kể cả chưa start)."""
    made: list = []

    def make(options) -> object:
        from teleport.ui.bridge import NodeHost

        host = NodeHost(options)
        made.append(host)
        return host

    yield make

    for host in made:
        with contextlib.suppress(Exception):
            host.stop()
    deadline = time.monotonic() + 30
    for host in made:
        # `join` chặn thread Qt: cho event loop chạy giữa các lần chờ để tín hiệu xếp hàng được xử lý.
        while not host.join(0.05):
            qtbot.wait(20)
            assert time.monotonic() < deadline, "thread node không dừng sau 30 s"


@pytest.fixture
def fast_lock(monkeypatch):
    """`node.lock` bị giữ thì `Node.start` báo ngay (LOCK_TIMEOUT nhỏ)."""
    from teleport.app import node as app_node

    monkeypatch.setattr(app_node, "LOCK_TIMEOUT", 0.2)


# =================================================================================================
# Chạy `main()` trong tiến trình
# =================================================================================================


class OsExitCalled(BaseException):
    pass


class Wait:
    """Bước chờ của kịch bản: `yield Wait(lambda: …, 5, "mô tả")`."""

    def __init__(self, predicate: Callable[[], object], timeout: float = 10.0, what: str = "điều kiện"):
        self.predicate = predicate
        self.timeout = timeout
        self.what = what


class GuiRun:
    """Một lần chạy `main(argv)` trong tiến trình, điều khiển bằng kịch bản.

    `script(run)` là generator chạy trong event loop Qt (QTimer 20 ms): `yield Wait(pred, timeout, what)`
    để chờ, `yield` trơn để nhường một nhịp. Kịch bản lỗi hay hết hạn → ghi lỗi, `QApplication.quit()`,
    rồi lỗi được ném lại sau khi `main` trả về. `run.hosts`, `run.trays`, `run.windows`: đối tượng
    được tạo, theo thứ tự; `run.stop_calls`: số lần `NodeHost.stop()`; `run.messages`: các lần
    `QSystemTrayIcon.showMessage` (tiêu đề, nội dung).
    """

    def __init__(self) -> None:
        self.hosts: list = []
        self.trays: list = []
        self.windows: list = []
        self.stop_calls = 0
        self.start_calls = 0
        self.messages: list[tuple[str, str]] = []
        self.exec_calls: list[str] = []
        self.exec_texts: list[str] = []  # chữ của mỗi QMessageBox mở bằng exec() (đã bị chặn, trả 0)
        self.activations = 0
        self.error: BaseException | None = None
        self.script_done = False
        self.code: int | None = None
        self.quit_at: float | None = None
        self.returned_at: float | None = None

    @property
    def window(self):
        assert self.windows, "main chưa tạo MainWindow"
        return self.windows[-1]

    @property
    def host(self):
        assert self.hosts, "main chưa tạo NodeHost"
        return self.hosts[-1]

    @property
    def tray(self):
        assert self.trays, "main chưa tạo Tray"
        return self.trays[-1]


@pytest.fixture
def gui(qapp, monkeypatch, tmp_path):
    """`gui(argv, script, *, tray=True, timeout=60, keep_receive_dir=False) -> GuiRun` (đã chạy xong;
    `run.code` là mã thoát).

    `tray`: giá trị của seam `teleport.ui.tray.is_available`. Mặc định thư mục nhận của mọi node bị ép
    thành đường dẫn tường minh `tmp_path / "nhan-gui"`. `keep_receive_dir=True` (spec-b1b mục 11.2): giữ
    nguyên `options.receive_dir` của app (`ReceiveDirChoice.SAVED`: thư mục đã lưu trong
    `settings.json`, chưa lưu thì `paths.default_receive_dir()`, ở đây đã vá thành `tmp_path / "nhan-gui"`),
    chỉ ép host/cổng/mDNS. Gọi `gui` hai lần trong một test (khởi động lại) thì dùng cùng một giá trị.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QSystemTrayIcon

    from teleport import paths
    from teleport.ui import app as ui_app
    from teleport.ui import bridge, main_window, tray

    receive_dir = tmp_path / "nhan-gui"
    monkeypatch.setenv(paths.ENV_HOME, str(tmp_path / "home-khong-dung"))
    monkeypatch.setattr(paths, "default_receive_dir", lambda: receive_dir)
    monkeypatch.setattr(logging, "shutdown", lambda *a, **k: None)
    old_sigint = signal.getsignal(signal.SIGINT)
    old_quit_on_close = qapp.quitOnLastWindowClosed()
    runs: list[GuiRun] = []

    def run_gui(
        argv: list[str],
        script,
        *,
        tray_available: bool = True,
        timeout: float = 60.0,
        require_script_done: bool = True,
        keep_receive_dir: bool = False,
    ) -> GuiRun:
        """`require_script_done`: kịch bản phải chạy tới cuối (không thì `main` thoát giữa chừng mà test
        vẫn xanh rỗng). Tắt cho ca `main` thoát trước vòng sự kiện (ví dụ không lấy được bản chính)."""
        run = GuiRun()
        runs.append(run)

        def fake_exit(code=0):
            raise OsExitCalled(f"main gọi os._exit({code})")

        monkeypatch.setattr(os, "_exit", fake_exit)
        monkeypatch.setattr(tray, "is_available", lambda: tray_available)

        real_host_init = bridge.NodeHost.__init__
        real_host_start = bridge.NodeHost.start
        real_host_stop = bridge.NodeHost.stop

        def host_init(self, *args, **kwargs):
            if args:
                options, rest = args[0], args[1:]
            else:
                options, rest = kwargs.pop("options"), ()
            forced = {} if keep_receive_dir else {"receive_dir": receive_dir}
            options = dataclasses.replace(options, host=LOCAL, port=0, mdns=None, **forced)
            real_host_init(self, options, *rest, **kwargs)
            run.hosts.append(self)

        def host_start(self, *args, **kwargs):
            run.start_calls += 1
            return real_host_start(self, *args, **kwargs)

        def host_stop(self, *args, **kwargs):
            run.stop_calls += 1
            if run.quit_at is None:
                run.quit_at = time.monotonic()
            return real_host_stop(self, *args, **kwargs)

        monkeypatch.setattr(bridge.NodeHost, "__init__", host_init)
        monkeypatch.setattr(bridge.NodeHost, "start", host_start)
        monkeypatch.setattr(bridge.NodeHost, "stop", host_stop)

        real_tray_init = tray.Tray.__init__

        def tray_init(self, *args, **kwargs):
            real_tray_init(self, *args, **kwargs)
            run.trays.append(self)

        monkeypatch.setattr(tray.Tray, "__init__", tray_init)

        real_win_init = main_window.MainWindow.__init__

        def win_init(self, *args, **kwargs):
            real_win_init(self, *args, **kwargs)
            run.windows.append(self)

        monkeypatch.setattr(main_window.MainWindow, "__init__", win_init)

        real_activate = main_window.MainWindow.activateWindow

        def activate(self, *args, **kwargs):
            run.activations += 1
            return real_activate(self, *args, **kwargs)

        monkeypatch.setattr(main_window.MainWindow, "activateWindow", activate)

        def show_message(self, *args, **kwargs):
            title = args[0] if args else kwargs.get("title", "")
            body = args[1] if len(args) > 1 else kwargs.get("msg", kwargs.get("message", ""))
            run.messages.append((str(title), str(body)))

        monkeypatch.setattr(QSystemTrayIcon, "showMessage", show_message)

        # Nền `offscreen` không có khay thật: biểu tượng không bao giờ “hiện”. Khi test giả có khay, giả
        # luôn trạng thái hiện/ẩn của `QSystemTrayIcon` như một khay thật.
        if tray_available:
            shown: dict[int, bool] = {}
            monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: shown.__setitem__(id(self), True))
            monkeypatch.setattr(QSystemTrayIcon, "hide", lambda self: shown.__setitem__(id(self), False))
            monkeypatch.setattr(
                QSystemTrayIcon, "setVisible", lambda self, v: shown.__setitem__(id(self), bool(v))
            )
            monkeypatch.setattr(QSystemTrayIcon, "isVisible", lambda self: shown.get(id(self), False))

        def no_exec(name):
            def fake(self, *args, **kwargs):
                run.exec_calls.append(f"{type(self).__name__}.{name}")
                if isinstance(self, QMessageBox):
                    run.exec_texts.append("\n".join(t for t in (self.text(), self.informativeText()) if t))
                return 0

            return fake

        monkeypatch.setattr(QMessageBox, "exec", no_exec("exec"))
        monkeypatch.setattr(QDialog, "exec", no_exec("exec"))

        gen: Iterator = script(run)
        state: dict = {"wait": None}

        def fail(error: BaseException) -> None:
            if run.error is None:
                run.error = error
            ticker.stop()
            QApplication.quit()

        def tick() -> None:
            if run.script_done or run.error is not None:
                return
            try:
                waiting = state["wait"]
                if waiting is not None:
                    w, deadline = waiting
                    if not w.predicate():
                        if time.monotonic() > deadline:
                            raise AssertionError(f"hết {w.timeout} s mà chưa: {w.what}")
                        return
                    state["wait"] = None
                step = next(gen)
                if isinstance(step, Wait):
                    state["wait"] = (step, time.monotonic() + step.timeout)
            except StopIteration:
                run.script_done = True
            except BaseException as e:
                fail(e)

        ticker = QTimer()
        ticker.setInterval(20)
        ticker.timeout.connect(tick)
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(lambda: fail(AssertionError(f"main chưa trả về sau {timeout} s")))
        live = {"on": True}  # `main` trả về trước vòng sự kiện: hai hẹn giờ dưới không được chạy muộn

        def arm() -> None:
            if live["on"]:
                ticker.start()
                watchdog.start(int(timeout * 1000))

        QTimer.singleShot(0, arm)
        try:
            run.code = ui_app.main(argv)
        finally:
            live["on"] = False
            run.returned_at = time.monotonic()
            ticker.stop()
            watchdog.stop()
            with contextlib.suppress(Exception):
                gen.close()
        if run.error is not None:
            raise run.error
        if require_script_done:
            assert run.script_done, "main đã trả về khi kịch bản chưa chạy hết"
        return run

    yield run_gui

    # Dọn: host nào còn chạy thì dừng; khôi phục trạng thái dùng chung của QApplication.
    for run in runs:
        for host in run.hosts:
            with contextlib.suppress(Exception):
                host.stop()
            deadline = time.monotonic() + 30
            with contextlib.suppress(Exception):
                while not host.join(0.05) and time.monotonic() < deadline:
                    QApplication.processEvents()
        for w in run.windows:
            with contextlib.suppress(Exception):
                w.hide()
                w.deleteLater()
        for t in run.trays:
            with contextlib.suppress(Exception):
                t.deleteLater()
    for w in visible_message_boxes():
        with contextlib.suppress(Exception):
            w.close()
    QApplication.processEvents()
    qapp.setQuitOnLastWindowClosed(old_quit_on_close)
    signal.signal(signal.SIGINT, old_sigint)


@pytest.fixture
def gui_wait():
    """Lớp `Wait` cho kịch bản của `gui`."""
    return Wait


# =================================================================================================
# Máy gửi B: Node thật trong một thread có event loop riêng
# =================================================================================================


class PeerNode:
    """Một `Node` (máy B) chạy trong thread riêng. Mọi lời gọi tới node đi qua loop của nó.

    `name`: tên máy B tự xưng; nên trùng tên A đã lưu cho B, vì A cập nhật tên đã lưu theo `hello.name`
    khi kết nối điều khiển lên (A6).
    """

    def __init__(self, config: Path, name: str = "May-B") -> None:
        self.config = config
        self.name = name
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="test-peer-node", daemon=True)
        self.node = None
        self.updates: list = []
        self.events: list = []
        self._lock = threading.Lock()

    # Callback chạy trên loop của B.
    def _on_update(self, update) -> None:
        with self._lock:
            self.updates.append(update)

    def _on_event(self, event) -> None:
        with self._lock:
            self.events.append(event)

    def start(self) -> PeerNode:
        from teleport.app.node import Node

        self.thread.start()

        async def go():
            self.node = Node(
                self.config,
                name=self.name,
                host=LOCAL,
                port=0,
                on_event=self._on_event,
                on_transfer_event=self._on_update,
            )
            await self.node.start()

        self.run(go(), 20)
        return self

    def run(self, coro, timeout: float = 10.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def submit(self, coro):
        """Không chờ: trả `concurrent.futures.Future`."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def soon(self, fn, *args) -> None:
        self.loop.call_soon_threadsafe(fn, *args)

    @property
    def device_id(self) -> str:
        return self.node.identity.device_id

    def connected_to(self, device_id: str) -> bool:
        async def check() -> bool:
            return device_id in self.node.connected_devices()

        return self.run(check(), 5)

    def finished(self, transfer_id: str):
        with self._lock:
            for u in self.updates:
                if type(u).__name__ == "TransferFinished" and u.info.key.transfer_id == transfer_id:
                    return u
        return None

    def close(self) -> None:
        if self.node is not None:
            with contextlib.suppress(Exception):
                self.run(asyncio.wait_for(self.node.close(), 30), 35)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(10)
        if not self.thread.is_alive():
            self.loop.close()


@pytest.fixture
def peer_node():
    """`peer_node(config_dir, name="May-B") -> PeerNode` đã start; đóng khi test xong."""
    made: list[PeerNode] = []

    def make(config: Path, name: str = "May-B") -> PeerNode:
        peer = PeerNode(config, name)
        made.append(peer)
        return peer.start()

    yield make

    for peer in reversed(made):
        peer.close()


@pytest.fixture
def trust_each_other():
    """`trust_each_other(a, b, name_a="May-A", name_b="May-B")`: hai thư mục cấu hình tin nhau."""

    def run(a: Path, b: Path, name_a: str = "May-A", name_b: str = "May-B"):
        from teleport.trust.identity import load_or_create_identity, peer_cert_from_pem
        from teleport.trust.store import TrustStore

        id_a, id_b = load_or_create_identity(a), load_or_create_identity(b)
        TrustStore.load(a).add(peer_cert_from_pem(id_b.cert_pem()), name_b)
        TrustStore.load(b).add(peer_cert_from_pem(id_a.cert_pem()), name_a)
        return id_a, id_b

    return run


# =================================================================================================
# Theme sáng/tối cho test widget và test chụp ảnh (spec A3, mục 2.6)
# =================================================================================================


@pytest.fixture
def ui_theme(qapp):
    """`ui_theme(dark) -> Tokens`: `theme.apply(qapp, Dark/Light)`, trả token của chế độ đó.

    Gọi được nhiều lần trong một test. Teardown khôi phục `qapp.palette()`, `qapp.styleSheet()` và tên
    style lưu lúc dựng fixture. Khi đang có stylesheet, `qapp.style()` là proxy QStyleSheetStyle (tên
    rỗng), nên tên style thật đọc sau khi tạm gỡ stylesheet.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette

    from teleport.ui import theme

    old_palette = QPalette(qapp.palette())
    old_css = qapp.styleSheet()
    if old_css:
        qapp.setStyleSheet("")
    old_style = qapp.style().name()
    if old_css:
        qapp.setStyleSheet(old_css)

    def run(dark: bool):
        theme.apply(qapp, Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light)
        return theme.tokens(dark)

    yield run

    qapp.setStyleSheet("")
    if old_style:
        qapp.setStyle(old_style)
        qapp.setProperty(theme._STYLE_PROPERTY, None)  # để `theme` đặt lại Fusion ở lần áp sau
    qapp.setPalette(old_palette)
    qapp.setStyleSheet(old_css)
