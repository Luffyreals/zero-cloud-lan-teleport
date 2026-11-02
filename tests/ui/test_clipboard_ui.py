"""Clipboard ở khay, Cài đặt và luồng chat (spec D5 mục 3.3–3.5, ca test #7; mục 9 thắng: 9.1 điểm 6, 7).

Viết từ spec, không từ code. Không node, không socket.

- **Khay** (`ui/tray.py`, 3.4 + 9.1.6): `tray_safe` (`<`→`‹`, `>`→`›`, `&`→`＆`); tooltip ba câu clipboard;
  tên máy kia trong tooltip không còn `<`, `>`, `&`; ngân sách **127 đơn vị UTF-16** cho ca xấu nhất (tên 32
  cột toàn emoji + “Đang truyền 999 lượt”), VN và EN; dấu `CLIPBOARD` chỉ khi `received`, thứ tự ưu tiên
  UNAVAILABLE > PAUSED > CLIPBOARD > TRANSFERRING > NONE, hình khác các dấu khác; dấu và dòng tooltip tắt sau
  5 s, thông báo mới đếm lại; không bong bóng; dòng tạm dừng mới.
- **Cài đặt** (3.3 + 9.1.7): ô `syncClipboard` “Đồng bộ clipboard” giữa “Hỏi trước khi nhận” và “Hủy ghép
  đôi…”, tên trợ năng, `focus_widgets`, `set_clipboard` không phát signal, signal cấp dòng và cấp trang;
  controller gọi `node.set_clipboard`, lỗi lưu thì ô quay về + InfoBar, `KeyError` im lặng đọc lại; câu mô tả.
- **Chat** (3.5): `ChatView.show_clipboard`; một note mỗi luồng, xuống cuối; không vào `rows`/`row`/
  `active_count`/lịch sử; không ghi đĩa; `content_changed`; câu dòng 1/2, tên trợ năng, ký tự điều khiển →
  U+FFFD, `PlainText`; ảnh “Ảnh {w} × {h} · {size}”; “Thử lại” phát `retry_clipboard_requested(id)`.
- **Sửa sau soat-code**: dòng cảnh báo tooltip khay không bao giờ bị cắt (bỏ dòng clipboard rồi “Đang
  truyền” trước); kết quả “Thử lại” không áp lên note đã thay note được bấm.

Giả định (spec không nêu tên): `ClipNotice(kind, label)` với `kind` là chuỗi hay StrEnum giá trị
`received`/`too_large`/`write_failed` (test đọc kiểu của trường để dựng đúng); `TrayState(clipboard=…)`;
`ClipboardNote` ở `ui.chat_bubbles` (hay `ui.chat`); seam thời lượng 5 s: hằng cấp module của `ui.tray` có
“CLIP” trong tên, giá trị 5000 (ms) hay 5 (giây); không có thì test đợi thật 5 s.
"""

from __future__ import annotations

import builtins
import contextlib
import datetime
import hashlib
import os
import time
import typing
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QVBoxLayout, QWidget

APP_NAME = "ZCL Teleport"
PEER_ID = "a71c04d2" + "e" * 24
OTHER_ID = "0f0f0f0f" + "1" * 24
PEER = "PC-Nha"
OTHER = "Laptop-Minh"

# ---- Chữ của spec D5 --------------------------------------------------------------------------------
TIP_RECEIVED = "Vừa nhận clipboard từ {name}"
TIP_WRITE_FAILED = "Chưa chép được clipboard từ {name}"
TIP_TOO_LARGE = "Clipboard quá lớn nên không gửi. Hãy gửi dạng file."
TIP_PAUSED = "Đã tạm dừng nhận file mới và clipboard"
TOOLTIP_UTF16_BUDGET = 127  # 9.1.6

SYNC_CLIPBOARD = "Đồng bộ clipboard"
ASK = "Hỏi trước khi nhận"
TRUSTED_DESCRIPTION = (
    "Các máy đã ghép đôi với máy này. Bỏ chọn “Hỏi trước khi nhận” để tự nhận file từ máy đó. Clipboard chỉ "
    "đồng bộ khi cả hai máy cùng bật “Đồng bộ clipboard”; mật khẩu chép từ trình quản lý mật khẩu không được "
    "gửi."
)
SETTINGS_ERROR = (
    "Chưa lưu được cài đặt vì không ghi được vào thư mục cấu hình của Teleport. Hãy kiểm tra quyền ghi "
    "rồi thử lại."
)
OTHER_ERROR = "Chưa lưu được cài đặt vì một lỗi không mong đợi. Hãy thử lại."

NOTE_OK = "Clipboard · đã chép vào máy này"
NOTE_FAILED = "Clipboard · chưa chép được vào máy này"
RETRY = "Thử lại"
NOTE_IMAGE = "Ảnh {w} × {h} · {size}"
NOTE_NAME = "Clipboard từ {name}: {line1}. {line2}"

# Tên máy kia hợp lệ trên dây (≤ 64 code point, `validate_device_name`), ≤ 32 cột sau `display_name`.
EMOJI_16 = "😀" * 16  # 32 cột, 32 đơn vị UTF-16
EMOJI_VS_ZWJ = "😀️‍" * 15 + "😀️"  # 32 cột, 47 code point, 62 đơn vị UTF-16
EMOJI_FAMILY = "👨‍👩‍👧‍👦" * 4  # 32 cột, 28 code point, 44 đơn vị
EMOJI_LONG = "🚀" * 64  # bị cắt còn 15 emoji + “…”
WORST_NAMES = {"emoji16": EMOJI_16, "emoji-vs-zwj": EMOJI_VS_ZWJ, "family": EMOJI_FAMILY, "long": EMOJI_LONG}
# Ký tự Mn ngoài BMP (bộ chọn biến thể bổ sung U+E0100): 0 cột, 2 đơn vị UTF-16. 64 code point, 2 cột.
MN_SUPPLEMENTARY = "😀" + "\U000e0100" * 63


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def settle(qtbot=None, ms: int = 0) -> None:
    for _ in range(3):
        QApplication.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if qtbot is not None and ms:
        qtbot.wait(ms)


def plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


# =================================================================================================
# Khay
# =================================================================================================


def notice(kind: str, label: str):
    """`ClipNotice(kind, label)`; `kind` dựng theo kiểu khai báo của trường (StrEnum hay chuỗi)."""
    from teleport.ui import tray as mod

    hints = typing.get_type_hints(mod.ClipNotice, vars(mod))
    kind_type = hints.get("kind")
    value: object = kind
    if isinstance(kind_type, type) and issubclass(kind_type, str) and kind_type is not str:
        value = kind_type(kind)
    return mod.ClipNotice(value, label)


def state(**kw):
    from teleport.ui.tray import TrayState

    return TrayState(**kw)


def name_label(name: str, device_id: str = PEER_ID) -> str:
    from teleport.ui.texts import peer_label

    return peer_label(name, device_id)


def test_tray_safe_replaces_markup_characters():
    from teleport.ui.tray import tray_safe

    assert tray_safe("<b>Nhà & Cửa</b>") == "‹b›Nhà ＆ Cửa‹/b›"
    assert tray_safe("&amp;&lt;") == "＆amp;＆lt;"
    assert tray_safe("PC-Nha") == "PC-Nha"
    assert tray_safe("") == ""


@pytest.mark.parametrize(
    ("kind", "template"),
    [("received", TIP_RECEIVED), ("write_failed", TIP_WRITE_FAILED)],
)
def test_tooltip_has_clipboard_line_with_peer_name(qapp, kind, template):
    from teleport.ui.tray import tray_tooltip

    tip = tray_tooltip(state(running=True, clipboard=notice(kind, name_label(PEER))))
    lines = tip.split("\n")
    assert lines[0] == APP_NAME
    assert template.format(name=PEER) in lines


def test_tooltip_too_large_line(qapp):
    from teleport.ui.tray import tray_tooltip

    tip = tray_tooltip(state(running=True, clipboard=notice("too_large", "")))
    assert TIP_TOO_LARGE in tip.split("\n")


@pytest.mark.parametrize("kind", ["received", "write_failed"])
def test_tooltip_peer_name_markup_is_neutralised(qapp, kind):
    """B5: tên máy kia chứa thẻ HTML / thực thể không lọt nguyên vào tooltip khay (rich text trên X11)."""
    from teleport.ui.tray import tray_tooltip

    raw = "<b>Nhà</b> &amp; <img src=x>"
    tip = tray_tooltip(state(running=True, clipboard=notice(kind, name_label(raw))))
    line = tip.split("\n")[1]
    assert "<" not in line and ">" not in line and "&" not in line, line
    assert "‹b›Nhà‹/b› ＆amp; ‹img src=x›" in line


def test_tooltip_paused_line_mentions_clipboard(qapp):
    from teleport.ui.tray import tray_tooltip

    assert TIP_PAUSED in tray_tooltip(state(running=True, paused=True)).split("\n")


@pytest.mark.parametrize("lang", ["vi", "en"])
@pytest.mark.parametrize("kind", ["received", "write_failed", "too_large"])
@pytest.mark.parametrize("name", list(WORST_NAMES.values()), ids=list(WORST_NAMES))
def test_tooltip_worst_case_within_utf16_budget(qapp, lang, kind, name):
    """9.1.6: tên 32 cột toàn emoji + dòng “Đang truyền” ≤ 127 đơn vị UTF-16, VN và EN."""
    from teleport.ui import i18n
    from teleport.ui.tray import tray_tooltip

    if lang == "en":
        i18n.set_language("en")
    label = name_label(name)
    tip = tray_tooltip(state(running=True, active=999, clipboard=notice(kind, label)))
    assert utf16_len(tip) <= TOOLTIP_UTF16_BUDGET, (lang, kind, utf16_len(tip), tip)
    if kind != "too_large":
        assert any(label in line or label[:4] in line for line in tip.split("\n")[1:]), (
            "tên máy kia vẫn có trong tooltip"
        )


@pytest.mark.parametrize("lang", ["vi", "en"])
def test_tooltip_name_of_zero_width_supplementary_marks_within_budget(qapp, lang):
    """Tên hợp lệ 64 code point chỉ 2 cột mà 128 đơn vị UTF-16 (emoji + U+E0100 lặp lại): tooltip vẫn
    ≤ 127 đơn vị (Windows cắt ở 127, 9.1.6 đếm UTF-16 chứ không đếm cột)."""
    from teleport.core.messages import validate_device_name
    from teleport.ui import i18n
    from teleport.ui.tray import tray_tooltip

    validate_device_name(MN_SUPPLEMENTARY)  # tên này máy kia gửi được
    if lang == "en":
        i18n.set_language("en")
    tip = tray_tooltip(
        state(running=True, active=999, clipboard=notice("received", name_label(MN_SUPPLEMENTARY)))
    )
    assert utf16_len(tip) <= TOOLTIP_UTF16_BUDGET, (lang, utf16_len(tip))


@pytest.mark.parametrize("lang", ["vi", "en"])
@pytest.mark.parametrize("kind", ["received", "write_failed", "too_large"])
@pytest.mark.parametrize(("paused", "unavailable"), [(True, False), (False, True)])
def test_tooltip_every_line_at_once_within_utf16_budget(qapp, lang, kind, paused, unavailable):
    """Ngân sách 127 cho mọi tổ hợp trạng thái (đang truyền + tạm dừng/không nhận + clipboard), không chỉ ca
    spec nêu: “Clipboard quá lớn” vẫn xảy ra khi đang tạm dừng nhận (tạm dừng không chặn gửi)."""
    from teleport.ui import i18n
    from teleport.ui.tray import tray_tooltip

    if lang == "en":
        i18n.set_language("en")
    st = state(
        running=True,
        active=999,
        paused=paused,
        unavailable=unavailable,
        clipboard=notice(kind, name_label(EMOJI_16)),
    )
    tip = tray_tooltip(st)
    assert utf16_len(tip) <= TOOLTIP_UTF16_BUDGET, (lang, kind, paused, unavailable, utf16_len(tip), tip)


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"clipboard": "received"}, "clipboard"),
        ({"clipboard": "received", "active": 2}, "clipboard"),
        ({"clipboard": "received", "paused": True}, "paused"),
        ({"clipboard": "received", "unavailable": True}, "unavailable"),
        ({"clipboard": "received", "paused": True, "unavailable": True}, "unavailable"),
        ({"clipboard": "too_large"}, "none"),
        ({"clipboard": "write_failed"}, "none"),
        ({"clipboard": "too_large", "active": 1}, "transferring"),
        ({"clipboard": "write_failed", "active": 1}, "transferring"),
    ],
)
def test_badge_priority_with_clipboard(qapp, kw, expected):
    from teleport.ui.tray import tray_badge

    kw = dict(kw)
    kw["clipboard"] = notice(kw["clipboard"], PEER)
    assert tray_badge(state(running=True, **kw)) == expected


def test_badge_clipboard_none_when_not_running(qapp):
    from teleport.ui.tray import tray_badge

    assert tray_badge(state(running=False, clipboard=notice("received", PEER))) == "none"


def test_clipboard_badge_icon_differs_from_other_badges(qapp):
    from PySide6.QtGui import QImage

    from teleport.ui.tray import TrayBadge, make_icon

    def img(badge):
        return make_icon(badge).pixmap(32, 32).toImage().convertToFormat(QImage.Format.Format_ARGB32)

    clip = img(TrayBadge.CLIPBOARD)
    for other in TrayBadge:
        if other is not TrayBadge.CLIPBOARD:
            assert clip != img(other), f"dấu CLIPBOARD phải khác {other}"


@pytest.fixture
def tray(qapp, monkeypatch):
    """`Tray` đứng riêng, có khay giả; ghi lại mọi `showMessage`."""
    from PySide6.QtWidgets import QSystemTrayIcon

    from teleport.ui import tray as mod

    shown: dict[int, bool] = {}
    messages: list[tuple] = []
    monkeypatch.setattr(mod, "is_available", lambda: True)
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: shown.__setitem__(id(self), True))
    monkeypatch.setattr(QSystemTrayIcon, "hide", lambda self: shown.__setitem__(id(self), False))
    monkeypatch.setattr(QSystemTrayIcon, "setVisible", lambda self, v: shown.__setitem__(id(self), bool(v)))
    monkeypatch.setattr(QSystemTrayIcon, "isVisible", lambda self: shown.get(id(self), False))
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda self, *a, **k: messages.append(a))
    t = mod.Tray()
    t.set_running(True)
    t.show()
    yield SimpleNamespace(tray=t, messages=messages)
    t.dispose()
    qapp.processEvents()


def _flash_ms(monkeypatch) -> int:
    """Thời lượng thông báo clipboard của khay (ms); có seam thì vá còn 400 ms."""
    from teleport.ui import tray as mod

    for attr, value in vars(mod).items():
        if "CLIP" not in attr.upper() or isinstance(value, bool) or not isinstance(value, int | float):
            continue
        if value == 5000:
            monkeypatch.setattr(mod, attr, 400)
            return 400
        if value == 5:
            monkeypatch.setattr(mod, attr, 0.4)
            return 400
    return 5000


def test_flash_clipboard_badge_and_tooltip_clear_after_timeout(tray, qtbot, monkeypatch):
    ms = _flash_ms(monkeypatch)
    t = tray.tray
    start = time.monotonic()
    t.flash_clipboard(notice("received", PEER))
    assert t.badge == "clipboard"
    assert TIP_RECEIVED.format(name=PEER) in t.tooltip().split("\n")
    qtbot.waitUntil(lambda: t.badge == "none", timeout=ms + 3000)
    elapsed = (time.monotonic() - start) * 1000
    assert elapsed >= ms * 0.8, f"tắt quá sớm: {elapsed:.0f} ms < {ms} ms"
    assert TIP_RECEIVED.format(name=PEER) not in t.tooltip()
    assert t.state.clipboard is None


def test_new_flash_restarts_countdown(tray, qtbot, monkeypatch):
    ms = _flash_ms(monkeypatch)
    t = tray.tray
    t.flash_clipboard(notice("received", PEER))
    qtbot.wait(int(ms * 0.6))
    t.flash_clipboard(notice("write_failed", OTHER))
    assert TIP_WRITE_FAILED.format(name=OTHER) in t.tooltip()
    assert TIP_RECEIVED.format(name=PEER) not in t.tooltip(), "thông báo mới thay thông báo cũ"
    qtbot.wait(int(ms * 0.6))  # quá mốc tắt của thông báo đầu
    assert TIP_WRITE_FAILED.format(name=OTHER) in t.tooltip(), "thông báo mới đếm lại từ đầu"
    qtbot.waitUntil(lambda: t.state.clipboard is None, timeout=ms + 3000)


def test_disposed_tray_ignores_pending_clipboard_timeout(tray, qtbot, monkeypatch):
    """Khay đã `dispose()` (menu bị xóa) không vẽ lại khi hẹn giờ thông báo clipboard tới (lỗi CI PR #110)."""
    ms = _flash_ms(monkeypatch)
    t = tray.tray
    t.flash_clipboard(notice("received", PEER))
    t.dispose()
    qtbot.wait(ms + 200)  # lỗi cũ: `_clear_clipboard` chạm QAction đã xóa → RuntimeError trong event loop
    t.set_running(False)
    t.set_activity(3)


def test_flash_clipboard_shows_no_balloon(tray, qtbot):
    t = tray.tray
    for kind in ("received", "write_failed", "too_large"):
        t.flash_clipboard(notice(kind, PEER))
    settle(qtbot, 50)
    assert tray.messages == [], "D5: không bong bóng cho clipboard"


def test_too_large_flash_has_no_badge(tray):
    t = tray.tray
    t.flash_clipboard(notice("too_large", ""))
    assert t.badge == "none"
    assert TIP_TOO_LARGE in t.tooltip().split("\n")


# =================================================================================================
# Cài đặt → Thiết bị tin cậy
# =================================================================================================


def dview(name: str, device_id: str | None = None):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id or hashlib.sha256(name.encode()).hexdigest()[:32],
        name=name,
        os="windows",
        paired=True,
        online=True,
        connected=False,
        addresses=("192.168.1.9",),
        port=47474,
    )


class FakeNode:
    def __init__(self) -> None:
        self.log: list[tuple] = []
        self._fail: dict[str, list] = {}
        self.devices_settings: dict = {}

    def fail(self, op: str, *errors) -> None:
        self._fail.setdefault(op, []).extend(errors)

    def _enter(self, op: str, *args) -> None:
        self.log.append((op, *args))
        queue = self._fail.get(op)
        if queue:
            error = queue.pop(0)
            if error is not None:
                raise error

    @property
    def accept_pairing(self) -> bool:
        return True

    @accept_pairing.setter
    def accept_pairing(self, value: bool) -> None:
        pass

    def snapshot(self):
        from teleport.ui.settings import SettingsSnapshot

        self._enter("read_snapshot")
        return SettingsSnapshot(
            name="May-A",
            visible=True,
            rate_limit=None,
            temp_retention_days=None,
            language=None,
            autostart=False,
            devices=dict(self.devices_settings),
        )

    def set_clipboard(self, device_id: str, enabled: bool) -> None:
        from dataclasses import replace

        from teleport.app.settings import DeviceSettings

        self._enter("set_clipboard", device_id, enabled)
        current = self.devices_settings.get(device_id, DeviceSettings())
        self.devices_settings[device_id] = replace(current, clipboard=enabled)

    def set_ask_before_receive(self, device_id: str, ask: bool) -> None:
        self._enter("set_ask_before_receive", device_id, ask)

    def device_settings(self, device_id: str):
        from teleport.app.settings import DeviceSettings

        self._enter("device_settings", device_id)
        return self.devices_settings.get(device_id, DeviceSettings())

    def set_ui_preferences(self, **kw) -> None:
        self._enter("set_ui_preferences", kw)


class Pending:
    def __init__(self, fn, on_done) -> None:
        self.fn = fn
        self.on_done = on_done
        self.ran = False


class FakeJob:
    done = False

    def cancel(self) -> None:
        pass


class FakeHost(QObject):
    started = Signal()
    stopped = Signal()

    def __init__(self, node: FakeNode) -> None:
        super().__init__()
        self.node = node
        self.calls: list[Pending] = []
        self.wait_pairing_open = False
        self.running = True
        self.node_name = "May-A"

    def call(self, fn, on_done=None) -> None:
        self.calls.append(Pending(fn, on_done))

    def submit(self, fn, on_done=None):
        self.calls.append(Pending(fn, on_done))
        return FakeJob()

    def apply_pairing_policy(self, node) -> None:
        pass

    def set_node_name(self, name: str) -> None:
        self.node_name = name

    def run_calls(self) -> None:
        while True:
            pending = [p for p in self.calls if not p.ran]
            if not pending:
                return
            for p in pending:
                p.ran = True
                try:
                    result = p.fn(self.node)
                except Exception as e:
                    result = e
                if p.on_done is not None:
                    p.on_done(result)


@pytest.fixture
def senv(qtbot, tmp_path, monkeypatch):
    """Trang Cài đặt + controller + host giả; một máy tin cậy `b` (clipboard tắt)."""
    from teleport.app.settings import DeviceSettings
    from teleport.ui import settings as ui_settings
    from teleport.ui.radar import DeviceListModel
    from teleport.ui.settings import SettingsController, SettingsPage

    monkeypatch.setattr(ui_settings, "read_snapshot", lambda node: node.snapshot())
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    model = DeviceListModel()
    page = SettingsPage(model)
    model.setParent(page)
    qtbot.addWidget(page)
    page.resize(980, 660)
    page.show()
    qtbot.waitExposed(page)
    c = SettingsController(
        page, cfg, message_parent=lambda: page, open_url=lambda u: None, log_files=lambda: []
    )
    node = FakeNode()
    host = FakeHost(node)
    c.attach(host)
    b = dview("May-B")
    node.devices_settings[b.device_id] = DeviceSettings(clipboard=False)
    model.reset([b])
    c.on_started(host)
    host.run_calls()
    settle(qtbot, 20)
    yield SimpleNamespace(page=page, model=model, c=c, host=host, node=node, b=b, qtbot=qtbot)
    with contextlib.suppress(Exception):
        c.shutdown()
    settle(qtbot)


def row_of(env):
    row = env.page.device_row(env.b.device_id)
    assert row is not None
    return row


def info_notice(page) -> tuple[object, str] | None:
    bar = page.info_bar
    if bar.isHidden():
        return None
    return bar.level, " ".join(t for t in (bar.title, bar.text) if t)


def test_row_has_sync_clipboard_checkbox_between_ask_and_unpair(senv):
    from PySide6.QtWidgets import QCheckBox

    row = row_of(senv)
    box = row.findChild(QCheckBox, "syncClipboard")
    assert box is not None and box is row.clipboard_checkbox
    assert plain(box.text()) == SYNC_CLIPBOARD
    assert box.accessibleName() == f"{SYNC_CLIPBOARD}: May-B"
    assert not box.isChecked(), "mặc định tắt"
    widgets = row.focus_widgets()
    assert widgets.index(row.ask_checkbox) < widgets.index(box) < widgets.index(row.unpair_button)
    assert box.isVisibleTo(row)
    xs = [w.mapTo(row, w.rect().topLeft()) for w in (row.ask_checkbox, box, row.unpair_button)]
    assert (xs[0].y(), xs[0].x()) < (xs[1].y(), xs[1].x()) < (xs[2].y(), xs[2].x()), "thứ tự hiển thị"


def test_snapshot_with_clipboard_on_checks_box(qtbot, senv):
    from teleport.app.settings import DeviceSettings

    senv.node.devices_settings[senv.b.device_id] = DeviceSettings(clipboard=True)
    senv.c.on_started(senv.host)
    senv.host.run_calls()
    settle(qtbot, 20)
    assert row_of(senv).clipboard_checkbox.isChecked()


def test_set_clipboard_on_row_does_not_emit(senv):
    row = row_of(senv)
    got: list = []
    row.clipboard_toggled.connect(lambda *a: got.append(a))
    senv.page.clipboard_toggled.connect(lambda *a: got.append(a))
    row.set_clipboard(True)
    assert row.clipboard_checkbox.isChecked()
    row.set_clipboard(False)
    assert got == []


def test_click_emits_row_and_page_signal(senv):
    row = row_of(senv)
    row_got: list = []
    page_got: list = []
    row.clipboard_toggled.connect(lambda *a: row_got.append(a))
    senv.page.clipboard_toggled.connect(lambda *a: page_got.append(a))
    row.clipboard_checkbox.click()
    assert row_got == [(senv.b.device_id, True)]
    assert page_got == [(senv.b.device_id, True)]


def test_controller_calls_set_clipboard(senv):
    row = row_of(senv)
    row.clipboard_checkbox.click()
    senv.host.run_calls()
    settle(senv.qtbot)
    ops = [e for e in senv.node.log if e[0] == "set_clipboard"]
    assert ops == [("set_clipboard", senv.b.device_id, True)]
    assert row.clipboard_checkbox.isChecked()
    assert info_notice(senv.page) is None


def test_controller_save_error_reverts_checkbox(senv):
    from teleport.app.settings import SettingsSaveError
    from teleport.ui.widgets import InfoLevel

    row = row_of(senv)
    senv.node.fail("set_clipboard", SettingsSaveError("không ghi được"))
    row.clipboard_checkbox.click()
    assert row.clipboard_checkbox.isChecked()
    senv.host.run_calls()
    settle(senv.qtbot)
    assert not row.clipboard_checkbox.isChecked(), "lưu lỗi → ô quay về giá trị đã xác nhận"
    assert info_notice(senv.page) == (InfoLevel.ERROR, SETTINGS_ERROR)


def test_controller_unexpected_error_reverts_checkbox(senv):
    from teleport.ui.widgets import InfoLevel

    row = row_of(senv)
    senv.node.fail("set_clipboard", ZeroDivisionError("bí mật"))
    row.clipboard_checkbox.click()
    senv.host.run_calls()
    settle(senv.qtbot)
    assert not row.clipboard_checkbox.isChecked()
    assert info_notice(senv.page) == (InfoLevel.ERROR, OTHER_ERROR)


def test_controller_error_after_success_reverts_to_confirmed_on(senv):
    """Bật (ổn) rồi tắt (lỗi) → ô quay về bật (giá trị đã xác nhận gần nhất)."""
    from teleport.app.settings import SettingsSaveError

    row = row_of(senv)
    row.clipboard_checkbox.click()
    senv.host.run_calls()
    senv.node.fail("set_clipboard", SettingsSaveError("x"))
    row.clipboard_checkbox.click()
    assert not row.clipboard_checkbox.isChecked()
    senv.host.run_calls()
    settle(senv.qtbot)
    assert row.clipboard_checkbox.isChecked()


def test_controller_keyerror_silent_and_rereads(senv):
    row = row_of(senv)
    before = len([e for e in senv.node.log if e[0] in ("read_snapshot", "device_settings")])
    senv.node.fail("set_clipboard", KeyError(senv.b.device_id))
    row.clipboard_checkbox.click()
    senv.host.run_calls()
    settle(senv.qtbot)
    assert info_notice(senv.page) is None
    after = len([e for e in senv.node.log if e[0] in ("read_snapshot", "device_settings")])
    assert after > before, "KeyError (máy vừa bị hủy ghép đôi): đọc lại cài đặt"


def test_trusted_section_description_mentions_clipboard(senv):
    texts = [lb.text() for lb in senv.page.findChildren(QLabel)]
    assert TRUSTED_DESCRIPTION in texts


# =================================================================================================
# Luồng chat
# =================================================================================================

NOW = datetime.datetime(2026, 11, 2, 9, 30).timestamp()


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def note_class():
    from teleport.ui import chat, chat_bubbles

    cls = getattr(chat_bubbles, "ClipboardNote", None) or getattr(chat, "ClipboardNote", None)
    assert cls is not None, "spec 3.5: lớp ClipboardNote"
    return cls


def notes(view, device_id: str = PEER_ID) -> list:
    import shiboken6

    thread = view.thread_for(device_id)
    if thread is None:
        return []
    return [n for n in thread.findChildren(note_class()) if shiboken6.isValid(n) and not n.isHidden()]


def note_texts(note) -> list[str]:
    return [lb.text() for lb in note.findChildren(QLabel) if not lb.isHidden() and lb.text()]


def note_buttons(note, text: str) -> list:
    return [b for b in note.findChildren(QAbstractButton) if plain(b.text()) == text and not b.isHidden()]


@pytest.fixture
def chat(qtbot, monkeypatch):
    from teleport.app.devices import DeviceView
    from teleport.ui import chat as chat_mod
    from teleport.ui.chat import ChatView
    from teleport.ui.radar import DeviceListModel

    monkeypatch.setattr(chat_mod, "_wall_now", Clock(NOW))
    host = QWidget()
    qtbot.addWidget(host)
    devices = DeviceListModel(host)

    def dv(device_id, name):
        return DeviceView(
            device_id=device_id,
            name=name,
            os="windows",
            paired=True,
            online=True,
            connected=True,
            addresses=("192.168.1.20",),
            port=47474,
        )

    devices.reset([dv(PEER_ID, PEER), dv(OTHER_ID, OTHER)])
    view = ChatView(devices, host)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(view)
    host.resize(720, 460)
    view.set_device_names({PEER_ID: PEER, OTHER_ID: OTHER})
    view.set_connected(PEER_ID, True)
    view.set_connected(OTHER_ID, True)
    host.show()
    qtbot.waitExposed(host)
    view.set_device(PEER_ID)
    settle()
    changes: list[int] = []
    view.content_changed.connect(lambda: changes.append(1))
    return SimpleNamespace(host=host, devices=devices, view=view, changes=changes, qtbot=qtbot)


def show_text(view, device_id=PEER_ID, *, ok=True, preview="xin chào", size=None):
    from teleport.core.messages import ClipKind

    view.show_clipboard(
        device_id,
        ok=ok,
        kind=ClipKind.TEXT,
        size=len(preview.encode()) if size is None else size,
        preview=preview,
        image_size=None,
    )
    settle()


def test_show_clipboard_ok_text_note(chat):
    show_text(chat.view, preview="xin chào\nthế giới")
    [note] = notes(chat.view)
    shown = note_texts(note)
    assert NOTE_OK in shown
    assert "xin chào" in shown, "dòng 2: dòng đầu của preview"
    assert not any("thế giới" in t for t in shown)
    assert note_buttons(note, RETRY) == [], "chép được thì không có “Thử lại”"
    assert note.accessibleName() == NOTE_NAME.format(name=PEER, line1=NOTE_OK, line2="xin chào")


def test_note_is_not_a_bubble_and_not_counted(chat):
    from teleport.ui.chat_bubbles import ChatBubble

    show_text(chat.view)
    [note] = notes(chat.view)
    assert not isinstance(note, ChatBubble)
    assert chat.view.rows() == []
    assert chat.view.active_count() == 0
    thread = chat.view.thread_for(PEER_ID)
    assert note not in thread.history_bubbles()


def test_show_clipboard_emits_content_changed(chat):
    show_text(chat.view)
    assert chat.changes, "note mới phát content_changed"


def test_one_note_per_thread_latest_wins(chat):
    show_text(chat.view, preview="cũ")
    show_text(chat.view, ok=False, preview="mới")
    show_text(chat.view, preview="mới nhất")
    [note] = notes(chat.view)
    shown = note_texts(note)
    assert NOTE_OK in shown and "mới nhất" in shown
    assert NOTE_FAILED not in shown and "cũ" not in shown


def test_notes_are_per_device(chat):
    show_text(chat.view, PEER_ID, preview="cho Nhà")
    show_text(chat.view, OTHER_ID, ok=False, preview="cho Minh")
    assert len(notes(chat.view, PEER_ID)) == 1
    assert len(notes(chat.view, OTHER_ID)) == 1
    assert "cho Nhà" in note_texts(notes(chat.view, PEER_ID)[0])
    assert NOTE_FAILED in note_texts(notes(chat.view, OTHER_ID)[0])


def test_note_moves_to_bottom_of_thread(chat):
    from teleport.app.transfers import TransferStatusChanged
    from teleport.core.messages import FileEntry
    from teleport.core.transfer import Direction, TransferInfo, TransferKey, TransferStatus

    show_text(chat.view, preview="đầu")
    k = TransferKey(PEER_ID, Direction.SEND, "c" * 32)
    info = TransferInfo(
        key=k,
        status=TransferStatus.TRANSFERRING,
        files=(FileEntry("a.bin", 10, 1_700_000_000_000),),
        names=("a.bin",),
        file_index=0,
        done_bytes=0,
        total_bytes=10,
    )
    chat.view.handle(TransferStatusChanged(info))
    show_text(chat.view, preview="sau")
    settle(chat.qtbot, 20)
    thread = chat.view.thread_for(PEER_ID)
    [note] = notes(chat.view)
    bubble = chat.view.row(k)
    assert bubble is not None
    note_y = note.mapTo(thread, note.rect().topLeft()).y()
    bubble_y = bubble.mapTo(thread, bubble.rect().topLeft()).y()
    assert note_y > bubble_y, "note mới nhất nằm cuối luồng"


def test_failed_note_retry_emits_signal(chat):
    show_text(chat.view, ok=False, preview="chưa chép")
    [note] = notes(chat.view)
    assert NOTE_FAILED in note_texts(note)
    [button] = note_buttons(note, RETRY)
    with chat.qtbot.waitSignal(chat.view.retry_clipboard_requested, timeout=1000) as blocker:
        button.click()
    assert blocker.args == [PEER_ID]
    assert note.accessibleName() == NOTE_NAME.format(name=PEER, line1=NOTE_FAILED, line2="chưa chép")


def test_note_preview_control_chars_and_markup_shown_plain(chat):
    show_text(chat.view, preview="<b>đậm</b>\x07\tcuối\nkhông hiện")
    [note] = notes(chat.view)
    labels = [lb for lb in note.findChildren(QLabel) if "đậm" in lb.text()]
    assert labels, note_texts(note)
    label = labels[0]
    assert label.textFormat() == Qt.TextFormat.PlainText
    assert label.text().startswith("<b>đậm</b>��cuối")
    assert "\x07" not in label.text() and "\t" not in label.text()
    assert "không hiện" not in label.text()


def test_note_long_preview_is_elided(chat):
    show_text(chat.view, preview="a" * 200)
    [note] = notes(chat.view)
    labels = [lb for lb in note.findChildren(QLabel) if lb.text().startswith("aaa")]
    assert labels and labels[0].text().endswith("…"), [lb.text() for lb in labels]


def test_image_note_line_two(chat):
    from teleport.core.messages import ClipKind
    from teleport.ui import texts

    size = 2_500_000
    chat.view.show_clipboard(
        PEER_ID, ok=True, kind=ClipKind.PNG, size=size, preview=None, image_size=(1920, 1080)
    )
    settle()
    [note] = notes(chat.view)
    line2 = NOTE_IMAGE.format(w=1920, h=1080, size=texts.format_size(size))
    assert line2 in note_texts(note)
    assert note.accessibleName() == NOTE_NAME.format(name=PEER, line1=NOTE_OK, line2=line2)


def test_note_does_not_write_to_disk(chat, monkeypatch):
    writes: list = []
    real_open = builtins.open
    real_os_open = os.open

    def spy_open(file, mode="r", *a, **k):
        if any(c in mode for c in "wax+"):
            writes.append(("open", str(file), mode))
        return real_open(file, mode, *a, **k)

    def spy_os_open(path, flags, *a, **k):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            writes.append(("os.open", str(path), flags))
        return real_os_open(path, flags, *a, **k)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(os, "open", spy_os_open)
    show_text(chat.view, preview="bí mật không ghi đĩa")
    show_text(chat.view, ok=False, preview="lần hai")
    monkeypatch.undo()
    assert writes == []


def test_note_survives_thread_switch_and_history_load(chat):
    """Chỉ trong phiên: rời luồng rồi quay lại (nạp lịch sử) vẫn còn note, và note không thành mục lịch sử."""
    show_text(chat.view, preview="còn đây")
    chat.view.set_device(OTHER_ID)
    settle(chat.qtbot, 20)
    chat.view.set_device(PEER_ID)
    settle(chat.qtbot, 20)
    chat.view.load_history(PEER_ID, [])
    settle()
    [note] = notes(chat.view)
    assert "còn đây" in note_texts(note)
    assert chat.view.rows() == []


NOTHING_TO_RETRY = "Clipboard này không còn để chép lại."


def test_retry_nothing_left_shows_sentence(chat):
    """3.5: kết quả `NOTHING_TO_RETRY` → “Clipboard này không còn để chép lại.” (API báo kết quả về
    `ChatView`: `finish_clipboard_retry(id, available=False)`, tên do giao-dien đặt)."""
    show_text(chat.view, ok=False, preview="chưa chép")
    [note] = notes(chat.view)
    note_buttons(note, RETRY)[0].click()
    chat.view.finish_clipboard_retry(PEER_ID, available=False)
    settle()
    [note] = notes(chat.view)
    assert any(NOTHING_TO_RETRY in t for t in note_texts(note)), note_texts(note)


def test_retry_available_again_lets_user_retry(chat):
    show_text(chat.view, ok=False, preview="chưa chép")
    got: list[str] = []
    chat.view.retry_clipboard_requested.connect(got.append)
    [note] = notes(chat.view)
    note_buttons(note, RETRY)[0].click()
    chat.view.finish_clipboard_retry(PEER_ID, available=True)
    settle()
    note_buttons(notes(chat.view)[0], RETRY)[0].click()
    assert got == [PEER_ID, PEER_ID]


async def test_retry_job_without_clipboard_sync_is_nothing_to_retry():
    """9.1.1: việc chạy trên thread node đọc `node.clipboard` ở đó; None (node không đồng bộ clipboard) →
    `NOTHING_TO_RETRY` (hàm `ui.app._retry_clipboard`, tên do giao-dien đặt)."""
    from teleport.app.clipboard import ClipOutcome
    from teleport.ui.app import _retry_clipboard

    assert (
        await _retry_clipboard(SimpleNamespace(clipboard=None), device_id=PEER_ID)
        is ClipOutcome.NOTHING_TO_RETRY
    )


async def test_retry_job_calls_retry_write_for_device():
    from teleport.app.clipboard import ClipOutcome
    from teleport.ui.app import _retry_clipboard

    calls: list[str] = []

    class Sync:
        async def retry_write(self, device_id: str):
            calls.append(device_id)
            return ClipOutcome.RECEIVED

    node = SimpleNamespace(clipboard=Sync())
    assert await _retry_clipboard(node, device_id=PEER_ID) is ClipOutcome.RECEIVED
    assert calls == [PEER_ID]


# =================================================================================================
# Sửa sau soat-code P5-2: dòng cảnh báo khay không bao giờ bị cắt; kết quả “Thử lại” không áp lên note mới
# =================================================================================================

LONG_PLAIN = "PC-Nha-" + "x" * 25  # 32 cột chữ thường


@pytest.mark.parametrize("lang", ["vi", "en"])
@pytest.mark.parametrize("kind", ["received", "write_failed", "too_large"])
@pytest.mark.parametrize("warning", ["paused", "unavailable"])
@pytest.mark.parametrize("active", [0, 2, 999])
@pytest.mark.parametrize(
    "name", [LONG_PLAIN, EMOJI_16, EMOJI_LONG, MN_SUPPLEMENTARY], ids=["plain", "emoji16", "long", "mn"]
)
def test_tooltip_warning_line_is_never_cut(qapp, lang, kind, warning, active, name):
    """Dòng “Không nhận file: …” / “Đã tạm dừng…” luôn còn nguyên câu; quá ngân sách thì rút gọn / bỏ dòng
    clipboard trước, rồi dòng “Đang truyền”."""
    from PySide6.QtCore import QCoreApplication

    from teleport.ui import i18n
    from teleport.ui.tray import tray_tooltip

    if lang == "en":
        i18n.set_language("en")
    t = QCoreApplication.translate
    if warning == "unavailable":
        expected = t("Tray", "Không nhận file: không mở được thư mục nhận")
    else:
        expected = t("Tray", "Đã tạm dừng nhận file mới và clipboard")
    st = state(
        running=True,
        active=active,
        paused=warning == "paused",
        unavailable=warning == "unavailable",
        clipboard=notice(kind, name_label(name)),
    )
    tip = tray_tooltip(st)
    lines = tip.split("\n")
    assert utf16_len(tip) <= TOOLTIP_UTF16_BUDGET, (utf16_len(tip), tip)
    assert lines[0] == APP_NAME
    assert lines[-1] == expected, tip
    if active:
        active_line = t("Tray", "Đang truyền %n lượt", None, active)
        if utf16_len("\n".join([APP_NAME, active_line, expected])) <= TOOLTIP_UTF16_BUDGET:
            assert active_line in lines, "dòng clipboard phải bị bỏ trước dòng “Đang truyền”"


@pytest.mark.parametrize("lang", ["vi", "en"])
def test_tooltip_shortened_name_keeps_ellipsis_and_warning(qapp, lang):
    from teleport.ui import i18n
    from teleport.ui.tray import tray_tooltip

    if lang == "en":
        i18n.set_language("en")
    tip = tray_tooltip(state(running=True, paused=True, clipboard=notice("received", name_label(EMOJI_LONG))))
    lines = tip.split("\n")
    assert utf16_len(tip) <= TOOLTIP_UTF16_BUDGET
    assert len(lines) == 3 and "…" in lines[1] and "🚀" in lines[1], tip


def test_tooltip_clipboard_line_dropped_when_no_room_for_name(qapp, monkeypatch):
    """Không còn chỗ cho dù một ký tự của tên: bỏ cả dòng clipboard (không để “… từ …”)."""
    from teleport.ui import tray as mod

    monkeypatch.setattr(mod, "TOOLTIP_MAX_UNITS", 90)
    tip = mod.tray_tooltip(
        state(running=True, active=999, unavailable=True, clipboard=notice("received", name_label(EMOJI_16)))
    )
    assert "clipboard" not in tip.lower(), tip
    assert tip.endswith("Không nhận file: không mở được thư mục nhận")


def test_retry_result_not_applied_to_replacing_note(chat):
    """Bấm “Thử lại” ở note A, note B (lỗi mới) thay A, rồi kết quả của A tới: B giữ nguyên."""
    show_text(chat.view, ok=False, preview="clip A")
    [note_a] = notes(chat.view)
    note_buttons(note_a, RETRY)[0].click()
    show_text(chat.view, ok=False, preview="clip B")
    [note_b] = notes(chat.view)
    assert note_b is not note_a
    chat.view.finish_clipboard_retry(PEER_ID, available=False)
    settle()
    assert not note_b.unavailable
    assert not any(NOTHING_TO_RETRY in t for t in note_texts(note_b))
    assert note_buttons(note_b, RETRY) and note_b.retry_button.isEnabled()


def test_retry_results_follow_click_order(chat):
    """A bấm, B thay A, B bấm: kết quả thứ nhất (của A) bỏ, kết quả thứ hai áp lên B."""
    show_text(chat.view, ok=False, preview="clip A")
    [note_a] = notes(chat.view)
    note_buttons(note_a, RETRY)[0].click()
    show_text(chat.view, ok=False, preview="clip B")
    [note_b] = notes(chat.view)
    note_buttons(note_b, RETRY)[0].click()
    assert not note_b.retry_button.isEnabled()
    chat.view.finish_clipboard_retry(PEER_ID, available=False)
    assert not note_b.unavailable and not note_b.retry_button.isEnabled(), "kết quả của A không áp lên B"
    chat.view.finish_clipboard_retry(PEER_ID, available=False)
    settle()
    assert note_b.unavailable


def test_retry_result_without_click_is_ignored(chat):
    show_text(chat.view, ok=False, preview="chưa bấm")
    [note] = notes(chat.view)
    chat.view.finish_clipboard_retry(PEER_ID, available=False)
    assert not note.unavailable
