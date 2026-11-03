"""Trang Cài đặt nối vào app, node thật trên 127.0.0.1 (spec D2 mục 1.7, 3 “Tiêu chí xong” 3; test 4.6).

Viết từ spec, không từ code. A là GUI chạy `teleport.ui.app.main` trong tiến trình (fixture `gui`); B (khi
cần) là một `Node` thật trong thread riêng. `GuiApp` được bắt bằng cách bọc `GuiApp.__init__`; trang là
`GuiApp.settings.page`, controller là `GuiApp.settings` (spec 1.7).

Kiểm: ⚙ và Ctrl+, mở Cài đặt, Esc quay lại; đổi tên → `settings.json` + thẻ máy này + tên host nhớ
(9.10); ẩn → client TLS ẩn danh nhận 0 byte, hiện lại → nhận `hello`; ẩn lúc khởi động → `accept_pairing`
False; bỏ “Hỏi trước khi nhận” → tự nhận lượt kế; hủy ghép đôi từ Cài đặt có/không ô xóa lịch sử; tốc độ
và ngưỡng dọn tạm lưu và hiện lại sau khi mở lại; xuất log thật ra zip có `info.txt`; ngôn ngữ đã lưu
áp lần sau; `--selftest` dựng `SettingsPage`; lỗi khởi động rồi Thử lại → trang nạp lại.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import os
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from typing import ClassVar

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from teleport.ui.main_window import SETTINGS_SHORTCUT

pytestmark = pytest.mark.integration

LOCAL = "127.0.0.1"
MB = 1048576
UNPAIR_YES = "Hủy ghép đôi"


# =================================================================================================
# Phụ trợ
# =================================================================================================


@pytest.fixture
def apps(monkeypatch):
    """Mọi `GuiApp` được dựng trong test, theo thứ tự."""
    from teleport.ui import app as ui_app

    made: ClassVar[list] = []
    real_init = ui_app.GuiApp.__init__

    def init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        made.append(self)

    monkeypatch.setattr(ui_app.GuiApp, "__init__", init)
    return made


def started(run) -> bool:
    return bool(run.hosts) and run.hosts[-1].running


def loaded(apps) -> bool:
    return bool(apps) and apps[-1].settings.page.name_edit.isEnabled()


def quit_via_tray(run, plain) -> None:
    [action] = [a for a in run.tray.actions() if not a.isSeparator() and plain(a.text()) == "Thoát"]
    action.trigger()


_UNREADABLE = object()


def on_disk(config: Path) -> dict | object:
    path = config / "settings.json"
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _UNREADABLE


def disk_value(config: Path, key: str) -> object:
    data = on_disk(config)
    return data.get(key, None) if isinstance(data, dict) else _UNREADABLE


def host_value(run, gui_wait, fn, what: str):
    """Kịch bản con: `fn(node)` qua `NodeHost.call`, trả kết quả."""
    got: list = []
    run.host.call(fn, got.append)
    yield gui_wait(lambda: got, 5, what)
    if isinstance(got[0], BaseException):
        raise got[0]
    return got[0]


def open_settings(run, gui_wait):
    from teleport.ui.main_window import Page

    window = run.window
    window.settings_button.setFocus(Qt.FocusReason.OtherFocusReason)
    window.settings_button.click()
    yield gui_wait(lambda: window.current_page is Page.SETTINGS, 3, "trang Cài đặt mở")


def show(page, name: str) -> None:
    from teleport.ui.settings import Section

    page.show_section(Section[name])
    QApplication.processEvents()


def anonymous_first_bytes(port: int, timeout: float = 3.0) -> bytes:
    """Client TLS ẩn danh (không chứng chỉ) tới A: byte ứng dụng đầu tiên nhận được trước khi A đóng."""
    from teleport.net import tls

    async def go() -> bytes:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(LOCAL, port, ssl=tls.client_context()), 5
        )
        try:
            return await asyncio.wait_for(reader.read(65536), timeout)
        except (ConnectionError, OSError, TimeoutError):
            return b""
        finally:
            with contextlib.suppress(Exception):
                writer.transport.abort()

    try:
        return asyncio.run(go())
    except (ConnectionError, OSError):
        return b""


class SaveDialog(QFileDialog):
    """`settings.dialog_factory` giả: QFileDialog thật không native; `open()` chỉ ghi lại."""

    made: ClassVar[list] = []

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        SaveDialog.made.append(self)

    def open(self, *args) -> None:
        pass

    def choose(self, path: Path) -> None:
        self.selectFile(str(path))
        self.accept()


class Peer:
    """Máy B: `Node` thật trong thread riêng, tự nhận, có thể gửi file."""

    def __init__(self, config: Path, receive_dir: Path) -> None:
        self.config = config
        self.receive_dir = receive_dir
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="test-settings-peer", daemon=True)
        self.node = None
        self.updates: list = []
        self._lock = threading.Lock()

    def _on_update(self, update) -> None:
        with self._lock:
            self.updates.append(update)

    def start(self) -> Peer:
        from teleport.app.node import Node

        self.thread.start()

        async def go():
            self.node = Node(
                self.config,
                name="May-B",
                host=LOCAL,
                port=0,
                receive_dir=self.receive_dir,
                auto_accept=True,
                on_transfer_event=self._on_update,
            )
            await self.node.start()

        self.run(go(), 20)
        return self

    def run(self, coro, timeout: float = 10.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def soon(self, fn, *args) -> None:
        self.loop.call_soon_threadsafe(fn, *args)

    def connected_to(self, device_id: str) -> bool:
        async def check() -> bool:
            return device_id in self.node.connected_devices()

        return self.run(check(), 5)

    def send(self, device_id: str, *paths: Path):
        return asyncio.run_coroutine_threadsafe(self.node.transfers.send(device_id, list(paths)), self.loop)

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
def peer(tmp_path):
    made: list[Peer] = []

    def make(config: Path) -> Peer:
        p = Peer(config, tmp_path / "nhan-B")
        made.append(p)
        return p.start()

    yield make
    for p in reversed(made):
        p.close()


@pytest.fixture
def pair(config_dir, trust_each_other):
    def make():
        a, b = config_dir("A"), config_dir("B")
        id_a, id_b = trust_each_other(a, b, name_a="May-A", name_b="May-B")
        return a, b, id_a.device_id, id_b.device_id

    return make


def history_entry(device_id: str, transfer_id: str):
    from teleport.core.history import HistoryEntry

    return HistoryEntry(
        direction="send",
        device_id=device_id,
        device_name="May-B",
        transfer_id=transfer_id,
        file_count=1,
        total_bytes=10,
        done_bytes=10,
        names=("x.txt",),
        result="done",
        finished_at=datetime.datetime(2026, 10, 30, tzinfo=datetime.UTC),
        saved_path=None,
    )


def history_ids(config: Path) -> list[str]:
    from teleport.app import history

    return [e.device_id for e in history.load(config).entries]


# =================================================================================================
# Mở trang, Esc, Ctrl+,
# =================================================================================================


def test_settings_button_and_ctrl_comma_open_page_esc_back(gui, gui_wait, config_dir, ui_helpers, apps):
    from teleport.ui.main_window import Page

    d = config_dir("A")
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: started(run) and loaded(apps), 15, "node chạy, trang nạp xong")
        window = run.window
        seen["visible"] = window.settings_button.isVisibleTo(window)
        seen["tip"] = window.settings_button.toolTip()
        yield from open_settings(run, gui_wait)
        seen["focus_nav"] = QApplication.focusWidget() is apps[-1].settings.page.nav
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
        yield gui_wait(lambda: window.current_page is Page.HOME, 3, "Esc về HOME")
        window.activateWindow()
        yield gui_wait(window.isActiveWindow, 3, "cửa sổ active")
        QTest.keyClick(window, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)
        yield gui_wait(lambda: window.current_page is Page.SETTINGS, 3, "Ctrl+, mở Cài đặt")
        apps[-1].settings.page.header.back_button.click()
        yield gui_wait(lambda: window.current_page is Page.HOME, 3, "Quay lại về HOME")
        quit_via_tray(run, ui_helpers.plain)

    run = gui(["--config-dir", str(d)], script)
    assert seen["visible"], "⚙ hiện khi chạy qua GuiApp"
    native = QKeySequence(SETTINGS_SHORTCUT).toString(QKeySequence.SequenceFormat.NativeText)
    assert native in seen["tip"], f"tooltip ⚙ có phím tắt: {seen['tip']!r}"
    assert seen["focus_nav"], "trang hiện thì tiêu điểm ở nav"
    assert run.code == 0


def test_page_cannot_open_before_running(gui, gui_wait, config_dir, ui_helpers, apps):
    """Trang chỉ mở ở RUNNING; trang dùng chung model thiết bị với cột trái (1.7, 9.15)."""
    from teleport.ui.main_window import Page

    d = config_dir("A")
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: apps and run.windows, 10, "GuiApp dựng xong")
        app = apps[-1]
        seen["model"] = (
            app.settings.page.model is run.window.devices if hasattr(app.settings.page, "model") else None
        )
        if not started(run):
            seen["early"] = run.window.open_page(Page.SETTINGS)
        yield gui_wait(lambda: started(run), 15, "node chạy")
        quit_via_tray(run, ui_helpers.plain)

    gui(["--config-dir", str(d)], script)
    assert seen.get("early") in (None, False)
    assert seen["model"] in (None, True)


# =================================================================================================
# Đổi tên, ẩn/hiện
# =================================================================================================


def test_rename_updates_machine_card_and_settings_json(gui, gui_wait, config_dir, ui_helpers, apps):
    d = config_dir("A")
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: started(run) and loaded(apps), 15, "trang nạp xong")
        yield from open_settings(run, gui_wait)
        page = apps[-1].settings.page
        show(page, "GENERAL")
        page.name_edit.setFocus()
        page.name_edit.setText("  May-Moi  ")
        QTest.keyClick(page.name_edit, Qt.Key.Key_Return)
        yield gui_wait(lambda: disk_value(d, "name") == "May-Moi", 5, "settings.json có tên mới")
        yield gui_wait(lambda: run.window.machine_card.name_label.text() == "May-Moi", 3, "thẻ máy này")
        seen["host_name"] = run.host.node_name
        seen["node_name"] = yield from host_value(run, gui_wait, lambda n: n.name, "tên node")
        seen["edit"] = page.name_edit.text()
        quit_via_tray(run, ui_helpers.plain)

    run = gui(["--config-dir", str(d)], script)
    assert seen["node_name"] == "May-Moi"
    assert seen["host_name"] == "May-Moi", "NodeHost.set_node_name (9.10)"
    assert seen["edit"] == "May-Moi"
    assert run.code == 0


def test_hide_anonymous_client_gets_no_hello_then_show_gets_hello(
    gui, gui_wait, config_dir, ui_helpers, apps
):
    d = config_dir("A")
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: started(run) and loaded(apps), 15, "trang nạp xong")
        port = yield from host_value(run, gui_wait, lambda n: n.port, "cổng của A")
        seen["visible_first"] = anonymous_first_bytes(port)
        yield from open_settings(run, gui_wait)
        page = apps[-1].settings.page
        show(page, "PRIVACY")
        page.visible_switch.click()  # ẩn
        yield gui_wait(lambda: disk_value(d, "visible") is False, 5, "settings.json visible=false")
        state = yield from host_value(run, gui_wait, lambda n: (n.visible, n.accept_pairing), "luật")
        seen["hidden_state"] = state
        seen["hidden"] = anonymous_first_bytes(port)
        page.visible_switch.click()  # hiện lại
        yield gui_wait(lambda: disk_value(d, "visible") in (True, None), 5, "settings.json visible lại")
        seen["shown_state"] = yield from host_value(
            run, gui_wait, lambda n: (n.visible, n.accept_pairing), "luật"
        )
        seen["shown"] = anonymous_first_bytes(port)
        quit_via_tray(run, ui_helpers.plain)

    run = gui(["--config-dir", str(d)], script)
    assert b"hello" in seen["visible_first"], "máy hiện gửi hello cho máy lạ"
    assert seen["hidden_state"] == (False, False)
    assert seen["hidden"] == b"", f"máy ẩn gửi {len(seen['hidden'])} byte cho kết nối ẩn danh"
    assert seen["shown_state"] == (True, True)
    assert b"hello" in seen["shown"]
    assert run.code == 0


def test_hidden_at_start_accept_pairing_false(gui, gui_wait, config_dir, ui_helpers, apps):
    d = config_dir("A")
    (d / "settings.json").write_text(json.dumps({"visible": False}), encoding="utf-8")
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: started(run) and loaded(apps), 15, "trang nạp xong")
        seen["state"] = yield from host_value(run, gui_wait, lambda n: (n.visible, n.accept_pairing), "luật")
        port = yield from host_value(run, gui_wait, lambda n: n.port, "cổng")
        seen["bytes"] = anonymous_first_bytes(port)
        seen["switch"] = apps[-1].settings.page.visible_switch.isChecked()
        quit_via_tray(run, ui_helpers.plain)

    run = gui(["--config-dir", str(d)], script)
    assert seen["state"] == (False, False)
    assert seen["bytes"] == b""
    assert seen["switch"] is False
    assert run.code == 0


# =================================================================================================
# Thiết bị tin cậy
# =================================================================================================


def test_ask_off_auto_accepts_next_offer(gui, gui_wait, pair, peer, tmp_path, ui_helpers, apps):
    from teleport.ui.settings import TrustedDeviceRow

    a, b, a_id, b_id = pair()
    p = peer(b)
    src = tmp_path / "nguon"
    src.mkdir()
    f = src / "tu-nhan.txt"
    f.write_bytes(b"x" * 1000)
    receive_dir = tmp_path / "nhan-gui"
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: started(run) and loaded(apps), 15, "trang nạp xong")
        port = yield from host_value(run, gui_wait, lambda n: n.port, "cổng")
        p.soon(p.node.connect_hint, a_id, [LOCAL], port)
        yield gui_wait(lambda: p.connected_to(a_id), 10, "B nối tới A")
        yield from open_settings(run, gui_wait)
        page = apps[-1].settings.page
        show(page, "DEVICES")
        yield gui_wait(
            lambda: [r for r in page.findChildren(TrustedDeviceRow) if r.device_id == b_id], 5, "hàng của B"
        )
        [row] = [r for r in page.findChildren(TrustedDeviceRow) if r.device_id == b_id]
        seen["before"] = row.ask_checkbox.isChecked()
        row.ask_checkbox.click()
        yield gui_wait(
            lambda: isinstance(on_disk(a), dict) and "devices" in on_disk(a),
            5,
            "settings.json có mục thiết bị",
        )
        seen["ask"] = yield from host_value(
            run, gui_wait, lambda n: n.device_settings(b_id).ask_before_receive, "ask_before_receive"
        )
        fut = p.send(a_id, f)
        yield gui_wait(lambda: (receive_dir / "tu-nhan.txt").exists(), 20, "A tự nhận file")
        yield gui_wait(fut.done, 10, "send() của B xong")
        seen["offers"] = list(apps[-1].transfers.offers.keys())
        quit_via_tray(run, ui_helpers.plain)

    run = gui(["--config-dir", str(a)], script)
    assert seen["before"] is True
    assert seen["ask"] is False
    assert seen["offers"] == [], "không hộp hỏi nào"
    assert (receive_dir / "tu-nhan.txt").read_bytes() == b"x" * 1000
    assert run.code == 0


def _unpair_from_settings(run, gui_wait, apps, b_id: str, a: Path, clear: bool, seen: dict):
    from teleport.ui.settings import TrustedDeviceRow

    yield gui_wait(lambda: started(run) and loaded(apps), 15, "trang nạp xong")
    yield from open_settings(run, gui_wait)
    page = apps[-1].settings.page
    show(page, "DEVICES")
    yield gui_wait(
        lambda: [r for r in page.findChildren(TrustedDeviceRow) if r.device_id == b_id], 5, "hàng B"
    )
    [row] = [r for r in page.findChildren(TrustedDeviceRow) if r.device_id == b_id]
    row.unpair_button.click()
    pairing = apps[-1].pairing
    yield gui_wait(
        lambda: pairing.unpair_box is not None and pairing.unpair_box.isVisible(), 3, "hộp hủy ghép đôi"
    )
    box = pairing.unpair_box
    seen["checked"] = box.checkBox() is not None and box.checkBox().isChecked()
    box.checkBox().setChecked(clear)
    [yes] = [b for b in box.buttons() if b.text().replace("&", "") == UNPAIR_YES]
    yes.click()
    from teleport.trust.store import TrustStore, TrustStoreError

    def b_gone() -> bool:
        # Luồng node đang thay trusted.json bằng os.replace: Windows có thể từ chối đọc đúng lúc đó.
        try:
            return TrustStore.load(a).get(b_id) is None
        except TrustStoreError:
            return False

    yield gui_wait(b_gone, 10, "trusted.json bỏ B")
    yield gui_wait(
        lambda: (
            not [
                r for r in page.findChildren(TrustedDeviceRow) if r.device_id == b_id and r.isVisibleTo(page)
            ]
        ),
        5,
        "hàng B tự bỏ",
    )


def test_unpair_from_settings_with_clear_history(gui, gui_wait, pair, tmp_path, ui_helpers, apps):
    from teleport.app import history

    a, _b, _a_id, b_id = pair()
    other = "c" * 32
    history.save(a, [history_entry(b_id, "1" * 32), history_entry(other, "2" * 32)])
    seen: dict = {}

    def script(run):
        yield from _unpair_from_settings(run, gui_wait, apps, b_id, a, True, seen)
        yield gui_wait(lambda: b_id not in history_ids(a), 10, "history.json bỏ mục của B")
        quit_via_tray(run, ui_helpers.plain)

    run = gui(["--config-dir", str(a)], script)
    assert seen["checked"] is True, "ô xóa lịch sử bật sẵn"
    assert history_ids(a) == [other], "chỉ xóa lịch sử với máy đã hủy ghép đôi"
    assert run.code == 0


def test_unpair_from_settings_keep_history_when_unchecked(gui, gui_wait, pair, tmp_path, ui_helpers, apps):
    from teleport.app import history

    a, _b, _a_id, b_id = pair()
    history.save(a, [history_entry(b_id, "1" * 32)])
    seen: dict = {}

    def script(run):
        yield from _unpair_from_settings(run, gui_wait, apps, b_id, a, False, seen)
        quit_via_tray(run, ui_helpers.plain)

    run = gui(["--config-dir", str(a)], script)
    assert history_ids(a) == [b_id], "bỏ chọn ô: giữ lịch sử"
    assert run.code == 0


# =================================================================================================
# Lưu và mở lại
# =================================================================================================


def test_rate_limit_and_retention_persist_and_show_after_restart(gui, gui_wait, config_dir, ui_helpers, apps):
    d = config_dir("A")
    seen: dict = {}

    def first(run):
        yield gui_wait(lambda: started(run) and loaded(apps), 15, "trang nạp xong")
        yield from open_settings(run, gui_wait)
        page = apps[-1].settings.page
        show(page, "TRANSFER")
        page.rate_checkbox.click()
        page.rate_spin.setFocus()
        page.rate_spin.setValue(7)
        QTest.keyClick(page.rate_spin, Qt.Key.Key_Return)
        page.retention_spin.setFocus()
        page.retention_spin.setValue(30)
        QTest.keyClick(page.retention_spin, Qt.Key.Key_Return)
        yield gui_wait(
            lambda: disk_value(d, "rate_limit") == 7 * MB and disk_value(d, "temp_retention_days") == 30,
            5,
            "settings.json có rate_limit và temp_retention_days",
        )
        state = yield from host_value(
            run, gui_wait, lambda n: (n.transfers.rate_limit, n.settings.temp_retention_days), "node"
        )
        seen["node"] = state
        quit_via_tray(run, ui_helpers.plain)

    def second(run):
        yield gui_wait(lambda: started(run) and len(apps) == 2 and loaded(apps), 15, "lần 2 nạp xong")
        page = apps[-1].settings.page
        seen["rate_checked"] = page.rate_checkbox.isChecked()
        seen["rate"] = page.rate_spin.value()
        seen["days"] = page.retention_spin.value()
        quit_via_tray(run, ui_helpers.plain)

    gui(["--config-dir", str(d)], first)
    gui(["--config-dir", str(d)], second)
    assert seen["node"] == (7 * MB, 30)
    assert seen["rate_checked"] is True
    assert seen["rate"] == pytest.approx(7.0)
    assert seen["days"] == 30


def test_language_saved_and_restored_next_start(gui, gui_wait, config_dir, ui_helpers, apps, monkeypatch):
    from teleport.ui import i18n

    d = config_dir("A")
    installs: list = []
    real_install = i18n.install

    def install(app, language=None):
        installs.append(language)
        return real_install(app, language)

    monkeypatch.setattr(i18n, "install", install)
    seen: dict = {}

    def first(run):
        yield gui_wait(lambda: started(run) and loaded(apps), 15, "trang nạp xong")
        yield from open_settings(run, gui_wait)
        page = apps[-1].settings.page
        show(page, "GENERAL")
        combo = page.language_combo
        index = combo.findData("vi")
        assert index >= 0, "có mục Tiếng Việt"
        combo.setCurrentIndex(index)
        combo.activated.emit(index)
        yield gui_wait(lambda: disk_value(d, "language") == "vi", 5, "settings.json language=vi")
        quit_via_tray(run, ui_helpers.plain)

    def second(run):
        yield gui_wait(lambda: started(run) and len(apps) == 2 and loaded(apps), 15, "lần 2 nạp xong")
        seen["combo"] = apps[-1].settings.page.language_combo.currentData()
        quit_via_tray(run, ui_helpers.plain)

    gui(["--config-dir", str(d)], first)
    gui(["--config-dir", str(d)], second)
    assert installs[0] is None, "lần đầu chưa lưu gì: theo hệ điều hành"
    assert installs[-1] == "vi", f"lần sau áp ngôn ngữ đã lưu: {installs}"
    assert seen["combo"] == "vi"


# =================================================================================================
# Xuất log, selftest, lỗi khởi động
# =================================================================================================


def test_export_logs_real_zip_has_info_txt(
    gui, gui_wait, config_dir, ui_helpers, apps, monkeypatch, tmp_path
):
    from teleport.ui import settings as ui_settings

    d = config_dir("A")
    SaveDialog.made = []
    monkeypatch.setattr(ui_settings, "dialog_factory", SaveDialog)
    dest = tmp_path / "xuat log" / "teleport-log.zip"
    dest.parent.mkdir()
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: started(run) and loaded(apps), 15, "trang nạp xong")
        yield from open_settings(run, gui_wait)
        page = apps[-1].settings.page
        show(page, "ADVANCED")
        page.export_button.click()
        yield gui_wait(lambda: SaveDialog.made, 3, "hộp lưu file")
        SaveDialog.made[-1].choose(dest)
        yield gui_wait(lambda: dest.exists() and not page.info_bar.isHidden(), 10, "zip đã ghi, có thông báo")
        seen["notice"] = " ".join((page.info_bar.title, page.info_bar.text))
        quit_via_tray(run, ui_helpers.plain)

    run = gui(["--config-dir", str(d)], script)
    with zipfile.ZipFile(dest) as z:
        names = z.namelist()
    assert "info.txt" in names
    assert run.exec_calls == [], "hộp lưu mở bằng open(), không exec()"
    assert "Đã lưu log vào" in seen["notice"]


@pytest.mark.slow
def test_selftest_builds_settings_page(tmp_path):
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["TELEPORT_HOME"] = str(tmp_path / "home")
    code = (
        "import sys\n"
        "from teleport.ui import settings\n"
        "made = []\n"
        "real = settings.SettingsPage.__init__\n"
        "def init(self, *a, **k):\n"
        "    real(self, *a, **k)\n"
        "    made.append(1)\n"
        "settings.SettingsPage.__init__ = init\n"
        "from teleport.ui.app import main\n"
        "rc = main(['--selftest'])\n"
        "print('SETTINGS_PAGES', len(made))\n"
        "raise SystemExit(rc)\n"
    )
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, timeout=60)
    out = p.stdout.decode("utf-8", "replace")
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    # _selftest dựng đúng một SettingsPage; so cả dòng để "10" không khớp nhầm.
    assert "SETTINGS_PAGES 1" in out.splitlines(), out
    assert b"Traceback" not in p.stderr


def test_page_closed_on_start_error_and_retry_reloads(gui, gui_wait, config_dir, ui_helpers, apps, fast_lock):
    from teleport.lock import NodeLock
    from teleport.ui.main_window import Page

    d = config_dir("A")
    holder = NodeLock(d)
    holder.acquire()
    seen: dict = {}

    def script(run):
        yield gui_wait(
            lambda: run.windows and ui_helpers.M2_HEAD in ui_helpers.all_text(run.window), 15, "M2"
        )
        window = run.window
        seen["button"] = window.settings_button.isVisibleTo(window)
        window.settings_button.click()
        seen["page_on_error"] = window.current_page
        seen["loaded_on_error"] = apps[-1].settings.page.name_edit.isEnabled()
        holder.release()
        [retry] = ui_helpers.buttons_with_text(window, ui_helpers.RETRY)
        retry.click()
        yield gui_wait(
            lambda: len(run.hosts) >= 2 and started(run) and loaded(apps), 15, "Thử lại: trang nạp"
        )
        seen["controller_host"] = (
            apps[-1].settings.host is run.hosts[-1] if hasattr(apps[-1].settings, "host") else True
        )
        quit_via_tray(run, ui_helpers.plain)

    try:
        run = gui(["--config-dir", str(d)], script)
    finally:
        holder.release()
    assert seen["page_on_error"] is Page.HOME, "lỗi khởi động: không mở được Cài đặt"
    assert seen["loaded_on_error"] is False
    assert seen["controller_host"] is True
    assert run.code == 0


# =================================================================================================
# Xóa lịch sử → luồng chat nạp lại (spec B3 mục 9.14)
# =================================================================================================


def test_history_cleared_reaches_chat_view(gui, gui_wait, config_dir, ui_helpers, apps, monkeypatch):
    """`history_cleared` của trang Cài đặt (None) và của `PairingController` (device_id) →
    `ChatView.invalidate_history` của luồng chat."""
    from teleport.ui.chat import ChatView

    calls: list = []
    real = ChatView.invalidate_history

    def record(self, device_id):
        calls.append(device_id)
        real(self, device_id)

    monkeypatch.setattr(ChatView, "invalidate_history", record)
    d = config_dir("A")

    def script(run):
        yield gui_wait(lambda: started(run) and loaded(apps), 15, "node chạy, trang nạp xong")
        app = apps[-1]
        app.settings.history_cleared.emit(None)
        app.pairing.history_cleared.emit("a" * 32)
        quit_via_tray(run, ui_helpers.plain)

    run = gui(["--config-dir", str(d)], script)
    assert calls == [None, "a" * 32]
    assert run.code == 0
