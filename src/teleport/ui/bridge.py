"""Cầu nối giữa thread Qt và node: `NodeHost` chạy `app.node.Node` trong một thread riêng.

Mô hình (docs/architecture.md mục 2): Qt ở thread chính; node chạy trong
`threading.Thread(daemon=False)` với một loop asyncio chuẩn (`asyncio.Runner`, giống CLI).
`Node` được dựng và dùng **chỉ** trong thread node. Thread Qt chỉ chạm tới node qua
`NodeHost.call` / `NodeHost.submit`: hàm được đưa sang loop bằng `call_soon_threadsafe`, nên
không bao giờ chạy lồng trong một lượt xử lý action list của `TransferEngine` (bẫy `_deferred`).
Mọi phương thức công khai dành cho thread Qt của `NodeHost` đều `assert` đang ở thread đã dựng nó
(thread Qt). Có ba ngoại lệ: `apply_pairing_policy` và `set_wait_pairing_open` chỉ gọi trên thread
node, bên trong `call` (xem đoạn Luật nhận yêu cầu ghép đôi); `options` là bất biến.

Chiều ngược lại: callback của node (`on_event`, `on_transfer_event`, `on_pairing_prompt`,
`on_pairing_finished`, `on_clipboard_event`) chạy trên loop, chỉ chuyển sự kiện về thread Qt và không
bao giờ raise: `on_pairing_prompt` raise thì lõi hủy phiên (`PROMPT_FAILED`), nên hộp hiện mã được mở
sau đó trên thread Qt và lỗi hiển thị (nếu có) nằm lại ở `ui`, không bay về phiên. Mọi thứ về thread Qt
đi qua một signal nội bộ nối kiểu `QueuedConnection` tới slot của chính `NodeHost` (sống ở
thread Qt), rồi slot đó mới phát các signal công khai. Nhờ vậy mọi slot, kể cả hàm thường hay
lambda, chạy trên thread Qt.

`submit` trả về một `SubmitJob`: `cancel()` (thread Qt) hủy task trên loop qua
`call_soon_threadsafe`; gọi khi task chưa kịp tạo thì `fn` không chạy, gọi sau khi xong hay khi node
đã dừng thì không làm gì. Bị hủy → `on_done(CancelledError())`. `done` (đọc trên thread Qt) thành
True khi `on_done` đã chạy, kể cả khi `submit` báo lỗi ngay vì node chưa chạy.

Lỗi không ai lấy trên loop (task, callback) đi qua `errorlog.loop_exception_handler`: chỉ ghi tên
loại lỗi và traceback (mvp N9).

**Luật nhận yêu cầu ghép đôi** (Q9 của spec C2, spec D2 mục 1.3 và 9.3): `Node` được dựng với
`accept_pairing=False` (đóng mặc định). Ngay sau khi `start()` xong, trên thread node và trước khi
post `started`, `NodeHost.apply_pairing_policy(node)` đặt `node.accept_pairing = node.visible or
đang mở “Chờ ghép đôi”`. Trạng thái “đang chờ ghép đôi” là một biến duy nhất của `NodeHost`
(`_wait_pairing_open`), chỉ đọc/ghi trên thread node: trang “Chờ ghép đôi” (`ui.wait_pairing`) đặt nó
bằng `set_wait_pairing_open(node, flag)` trong một `call` (đặt rồi áp lại luật ngay) mỗi lần trang mở
hay đóng; host mới bắt đầu với False. **Hợp đồng**: mọi chỗ đổi `visible` phải gọi
`node.set_visible(v)` rồi `host.apply_pairing_policy(node)` trong **cùng một** `host.call` (một khối
đồng bộ trên loop), nên không có lúc nào máy ẩn mà vẫn nhận yêu cầu ghép đôi (máy ẩn đang gửi `hello`
cho máy lạ qua `Node._allows_anonymous`). Khoảng trống chấp nhận được: từ lúc cổng mở tới hết
`start()`, `accept_pairing` còn False nên máy đang hiện chưa nhận ghép đôi trong vài trăm ms đó (máy
ẩn thì đúng luật). Hàm thuần `apply_pairing_policy(node, wait_pairing_open=...)` là bảng chân trị.

Vòng đời trong thread node: dựng `Node` (`accept_pairing=False`, xem trên; hỏi người dùng từng
`offer`), `start()`, áp luật nhận ghép đôi,
phát `started` hoặc `start_failed(mã, chi tiết)`, chờ lệnh dừng, rồi đóng như `cli._close_node`:
`close()` chạy trong task riêng, không bị hủy trước hạn `app.node.close_time_limit()` (zeroconf
dừng giữa chừng nếu task bị hủy sớm), quá hạn mới hủy. Hạn được đọc qua thuộc tính module
`app_node.close_time_limit` lúc dùng, để test vá được. Dừng lúc `start()` chưa xong thì gọi
`close()` (không hủy task start): `start()` tự dừng ở bước kế với RuntimeError; khi đã có lệnh
dừng thì mọi lỗi khởi động chỉ dẫn tới `stopped`, không phát `start_failed`. Thread kết thúc
(dừng có trật tự hay khởi động thất bại) thì phát `stopped` đúng một lần.

Thư mục nhận: mặc định `ReceiveDirChoice.SAVED` (thư mục đã lưu; chưa lưu thì thư mục mặc định);
thư mục đã lưu không mở được thì node vẫn chạy mà không nhận file, không phải lỗi khởi động. Path
tường minh (test) mà hỏng thì vẫn `start_failed(RECEIVE_DIR)`. Ngay trước khi báo `started`, thread
node đọc `node.transfers.receive_dir` và `node.receive_dir_error` (lỗi khi đọc → None, ghi tên loại
lỗi); `NodeHost.receive_dir` / `receive_dir_error` là **ảnh chụp lúc `started`** (trước đó None, sau
đó không đổi). Sau `started`, nguồn sự thật trên thread Qt là `ui.receive_dir.ReceiveDirController`.

`start_failed` mang mã `StartError` và chi tiết đã làm sạch (ký tự điều khiển thành `·`, có
giới hạn độ dài). Chi tiết theo mã: CONFIG_DIR `<đường dẫn>\\n<lỗi>`; RECEIVE_DIR đường dẫn;
PORT lỗi của hệ điều hành; OTHER tên kiểu lỗi; còn lại rỗng. Câu chữ ở `ui.texts.start_error`.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import functools
import logging
import threading
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar

from PySide6.QtCore import QObject, Qt, Signal, Slot

from teleport.app import node as app_node
from teleport.app.clipboard import ClipboardBackend, ClipboardEvent
from teleport.app.node import (
    ConfigDirError,
    MdnsOptions,
    Node,
    NodeEvent,
    ReceiveDirChoice,
    ReceiveDirUnavailable,
)
from teleport.app.pairing import PairingFinished, PairingPrompt
from teleport.app.transfers import TransferUpdate
from teleport.lock import NodeLockedError
from teleport.trust.identity import IdentityError
from teleport.trust.store import TrustStoreError
from teleport.ui import errorlog

R = TypeVar("R")

log = logging.getLogger(__name__)

_DETAIL_MAX = 300  # ký tự tối đa của chi tiết lỗi gửi kèm `start_failed`
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})
_SUBMIT_CANCEL_WAIT = 1.0  # giây chờ các việc `submit` dở bị hủy trước khi đóng node
_CANCEL_WAIT = 1.0  # giây chờ `close()` / `start()` bị hủy kết thúc


class StartError(StrEnum):
    """Mã lỗi khởi động node (`NodeHost.start_failed`)."""

    LOCKED = "locked"  # một node khác (ví dụ `teleport receive`) giữ `node.lock`
    CONFIG_DIR = "config_dir"
    IDENTITY = "identity"
    TRUST_STORE = "trust_store"
    RECEIVE_DIR = "receive_dir"
    PORT = "port"
    OTHER = "other"


@dataclass(frozen=True)
class NodeOptions:
    """Tham số dựng `Node` của giao diện. Test dùng `host="127.0.0.1"`, `port=0`, `mdns=None`.

    `receive_dir`: mặc định thư mục đã lưu (`ReceiveDirChoice.SAVED`); Path tường minh vẫn được (test,
    và thư mục người dùng chọn ở lần chạy đầu).
    `name`: tên thiết bị cho `Node(name=…)`; None thì node dùng tên đã lưu, chưa có thì hostname.
    `save_args` (lần chạy đầu, `ui.first_run`): `Node.start` lưu `name` (nếu có) trước khi quảng bá và
    lưu `receive_dir` (nếu là Path) ngay khi mở được; mặc định False (không lưu gì).
    `clipboard`: backend clipboard cho `Node(clipboard=…)` (`ui.clipboard_qt.QtClipboardBackend` khi
    chạy GUI thật, dựng trên thread Qt); None → node không đồng bộ clipboard (mặc định, test).
    """

    config_dir: Path
    receive_dir: Path | ReceiveDirChoice = ReceiveDirChoice.SAVED
    mdns: MdnsOptions | None = field(default_factory=lambda: MdnsOptions(advertise=True))
    host: str = "0.0.0.0"
    port: int | None = None
    name: str | None = None
    save_args: bool = False
    clipboard: ClipboardBackend | None = None


def _clean(text: str) -> str:
    """Chữ an toàn để hiện: ký tự điều khiển/vô hình thành `·`, cắt ở `_DETAIL_MAX` ký tự."""
    shown = "".join("·" if unicodedata.category(ch) in _HIDDEN_CATEGORIES else ch for ch in text)
    if len(shown) > _DETAIL_MAX:
        shown = shown[: _DETAIL_MAX - 1] + "…"
    return shown


def _os_error_text(error: OSError) -> str:
    return error.strerror or str(error) or type(error).__name__


def apply_pairing_policy(node: Node, *, wait_pairing_open: bool = False) -> None:
    """Thread node, đồng bộ: `node.accept_pairing = node.visible or wait_pairing_open`.

    Bảng chân trị của luật nhận ghép đôi (docstring module). Bên trong `NodeHost` luôn đi qua
    `NodeHost.apply_pairing_policy(node)`, nơi đọc biến “đang chờ ghép đôi” của host.
    """
    node.accept_pairing = bool(node.visible or wait_pairing_open)


def classify_start_error(error: BaseException) -> tuple[StartError, str]:
    """Đổi lỗi của `Node()` / `Node.start()` thành (mã, chi tiết đã làm sạch).

    Thứ tự kiểm như `cli._start_transfer_node`: NodeLockedError, IdentityError, TrustStoreError,
    ConfigDirError, ReceiveDirUnavailable, OSError còn lại (cổng), rồi mọi lỗi khác.
    """
    if isinstance(error, NodeLockedError):
        return StartError.LOCKED, ""
    if isinstance(error, IdentityError):
        return StartError.IDENTITY, ""
    if isinstance(error, TrustStoreError):
        return StartError.TRUST_STORE, ""
    if isinstance(error, ConfigDirError):
        return StartError.CONFIG_DIR, f"{_clean(str(error.path))}\n{_clean(_os_error_text(error.error))}"
    if isinstance(error, ReceiveDirUnavailable):
        return StartError.RECEIVE_DIR, _clean(str(error.path))
    if isinstance(error, OSError):
        return StartError.PORT, _clean(_os_error_text(error))
    log.error("node không khởi động được: %s", type(error).__name__)
    return StartError.OTHER, _clean(type(error).__name__)


class _State(enum.Enum):
    """Trạng thái của `NodeHost`, chỉ đọc/ghi trên thread Qt."""

    IDLE = enum.auto()
    STARTING = enum.auto()
    RUNNING = enum.auto()
    STOPPING = enum.auto()
    STOPPED = enum.auto()


class SubmitJob:
    """Một việc của `NodeHost.submit`: hủy được từ thread Qt, biết `on_done` đã chạy chưa.

    `_cancel_requested` và `_task` dùng chung giữa hai thread, đọc/ghi khi giữ `_guard`;
    `_done` chỉ thread Qt.
    """

    def __init__(self, host: NodeHost) -> None:
        self._host = host
        self._done = False
        self._guard = threading.Lock()
        self._cancel_requested = False
        self._task: asyncio.Future[Any] | None = None

    @property
    def done(self) -> bool:
        """`on_done` đã được gọi (đọc trên thread Qt)."""
        self._host._check_thread()
        return self._done

    def cancel(self) -> None:
        """Hủy việc (thread Qt). Đã xong, node đã dừng hay gọi lần nữa: không làm gì, không lỗi."""
        self._host._check_thread()
        if self._done:
            return
        with self._guard:
            if self._cancel_requested:
                return
            self._cancel_requested = True
        loop = self._host._current_loop()
        if loop is None:
            return  # node đã dừng hay đang dừng: task (nếu có) bị hủy cùng node
        with contextlib.suppress(RuntimeError):  # loop vừa đóng
            loop.call_soon_threadsafe(self._cancel_on_loop)

    # ---- Nội bộ --------------------------------------------------------------------------

    def _cancel_on_loop(self) -> None:
        """Thread node: hủy task nếu còn chạy."""
        with self._guard:
            task = self._task
        if task is not None and not task.done():
            task.cancel()

    def _cancel_pending(self) -> bool:
        with self._guard:
            return self._cancel_requested

    def _attach(self, task: asyncio.Future[Any]) -> bool:
        """Thread node: gắn task; False nếu lệnh hủy đã tới trước (bên gọi tự hủy task)."""
        with self._guard:
            if self._cancel_requested:
                return False
            self._task = task
            return True

    def _deliver(self, on_done: Callable[[Any], None] | None, result: Any) -> None:
        """Thread Qt: đánh dấu xong rồi gọi `on_done`."""
        self._done = True
        with self._guard:
            self._task = None
        if on_done is not None:
            on_done(result)


class NodeHost(QObject):
    """Giữ một `Node` trong thread riêng; dùng một lần: `start()`, rồi `stop()`.

    Signal (luôn phát trên thread Qt): `started`; `start_failed(mã StartError, chi tiết)`;
    `node_event(NodeEvent)`; `transfer_event(TransferUpdate)`; `pairing_prompt(PairingPrompt)`;
    `pairing_finished(PairingFinished)`; `clipboard_event(ClipboardEvent)`; `stopped` (thread node đã
    xong việc, `join` sẽ trả True ngay). `call` / `submit` khi node chưa chạy hoặc đang đóng thì báo
    `on_done(RuntimeError)`. `on_done` luôn được gọi trên thread Qt, sau khi hàm gọi đã trả về.
    """

    started = Signal()
    start_failed = Signal(str, str)
    node_event = Signal(object)
    transfer_event = Signal(object)
    pairing_prompt = Signal(object)  # PairingPrompt
    pairing_finished = Signal(object)  # PairingFinished
    clipboard_event = Signal(object)  # ClipboardEvent
    stopped = Signal()

    _relay = Signal(object)  # hàm không tham số, chạy trên thread Qt

    def __init__(self, options: NodeOptions, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._options = options
        self._owner = threading.get_ident()
        self._relay.connect(self._on_relay, Qt.ConnectionType.QueuedConnection)
        # Chỉ thread Qt.
        self._state = _State.IDLE
        self._thread: threading.Thread | None = None
        self._node_name: str | None = None
        self._receive_dir: Path | None = None
        self._receive_dir_error: Path | None = None
        # Dùng chung giữa hai thread, đọc/ghi khi giữ `_guard`.
        self._guard = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._stop_requested = False
        # Chỉ thread node.
        self._node: Node | None = None
        self._wait_pairing_open = False  # trang “Chờ ghép đôi” đang mở; luật nhận ghép đôi
        self._serving = False  # node đã chạy và chưa bắt đầu dừng
        self._jobs: set[asyncio.Future[Any]] = set()  # việc `submit` đang chạy

    # ---- API cho thread Qt ---------------------------------------------------------------

    @property
    def options(self) -> NodeOptions:
        return self._options

    @property
    def running(self) -> bool:
        """Node đã chạy (`started` đã phát) và chưa có lệnh dừng."""
        self._check_thread()
        return self._state is _State.RUNNING

    @property
    def is_stopped(self) -> bool:
        """`stopped` đã phát (hoặc đang chờ phát, nếu `stop()` gọi trước `start()`)."""
        self._check_thread()
        return self._state is _State.STOPPED

    @property
    def node_name(self) -> str | None:
        """Tên thiết bị của node (`Node.name`), có sau `started`; chưa qua `display_name`."""
        self._check_thread()
        return self._node_name

    @property
    def receive_dir(self) -> Path | None:
        """Thư mục nhận lúc `started` (ảnh chụp; trước đó None); None nếu node không nhận file."""
        self._check_thread()
        return self._receive_dir

    @property
    def receive_dir_error(self) -> Path | None:
        """Thư mục nhận đã lưu không mở được lúc `started` (ảnh chụp; trước đó None), hay None."""
        self._check_thread()
        return self._receive_dir_error

    def set_node_name(self, name: str) -> None:
        """Thread Qt: nhớ tên mới của node (sau `Node.set_name` thành công); chưa qua `display_name`."""
        self._check_thread()
        self._node_name = name

    def apply_pairing_policy(self, node: Node) -> None:
        """**Thread node** (bên trong `call`): áp luật nhận ghép đôi với biến “đang chờ ghép đôi” của host.

        Không nhận tham số từ bên gọi: “đang chờ ghép đôi” chỉ có một nguồn (`set_wait_pairing_open`).
        """
        apply_pairing_policy(node, wait_pairing_open=self._wait_pairing_open)

    def set_wait_pairing_open(self, node: Node, open_: bool) -> None:
        """**Thread node** (bên trong `call`): đặt “đang chờ ghép đôi” (trang ở `ui.wait_pairing`) rồi
        áp lại luật ngay."""
        self._wait_pairing_open = bool(open_)
        self.apply_pairing_policy(node)

    def start(self) -> None:
        """Mở thread node; kết quả báo qua `started` / `start_failed`. Gọi lần hai → RuntimeError."""
        self._check_thread()
        if self._state is not _State.IDLE:
            raise RuntimeError("NodeHost chỉ start được một lần")
        self._state = _State.STARTING
        self._thread = threading.Thread(target=self._thread_main, name="teleport-node", daemon=False)
        self._thread.start()

    def call(
        self,
        fn: Callable[[Node], R],
        on_done: Callable[[R | BaseException], None] | None = None,
    ) -> None:
        """Chạy `fn(node)` trên loop của node; kết quả hay lỗi (Exception) về `on_done` trên thread Qt."""
        self._check_thread()
        self._dispatch(self._run_call, fn, on_done)

    def submit(
        self,
        fn: Callable[[Node], Awaitable[R]],
        on_done: Callable[[R | BaseException], None] | None = None,
    ) -> SubmitJob:
        """Chạy coroutine `fn(node)` thành task trên loop của node; bị hủy khi node dừng.

        Trả `SubmitJob` để hủy việc (`cancel()`) hay hỏi `on_done` đã chạy chưa (`done`).
        """
        self._check_thread()
        job = SubmitJob(self)
        deliver = functools.partial(job._deliver, on_done)
        self._dispatch(functools.partial(self._run_submit, job=job), fn, deliver)
        return job

    def stop(self) -> None:
        """Yêu cầu dừng, không chặn; gọi nhiều lần không sao. Trước `start()` → phát `stopped` ngay."""
        self._check_thread()
        if self._state is _State.IDLE:
            self._state = _State.STOPPED
            self._post(self.stopped.emit)
            return
        if self._state in (_State.STOPPING, _State.STOPPED):
            return
        self._state = _State.STOPPING
        with self._guard:
            self._stop_requested = True
            loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            # RuntimeError: loop vừa đóng, thread đang kết thúc, `stopped` sẽ tới.
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(wake.set)

    def join(self, timeout: float) -> bool:
        """Chờ thread node kết thúc tối đa `timeout` giây; True nếu không còn thread nào chạy."""
        self._check_thread()
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    # ---- Nội bộ: thread Qt ---------------------------------------------------------------

    def _check_thread(self) -> None:
        assert threading.get_ident() == self._owner, "NodeHost chỉ được gọi từ thread Qt đã dựng nó"

    def _dispatch(self, runner: Callable[..., None], fn: Callable[[Node], Any], on_done: Any) -> None:
        if self._state is not _State.RUNNING:
            self._report(on_done, RuntimeError("node chưa chạy hoặc đang đóng"))
            return
        with self._guard:
            loop = self._loop
        if loop is None:
            self._report(on_done, RuntimeError("node chưa chạy hoặc đang đóng"))
            return
        try:
            loop.call_soon_threadsafe(runner, fn, on_done)
        except RuntimeError as e:  # loop vừa đóng
            self._report(on_done, e)

    def _current_loop(self) -> asyncio.AbstractEventLoop | None:
        """Thread Qt: loop của node khi node đang chạy (chưa có lệnh dừng), không thì None."""
        if self._state is not _State.RUNNING:
            return None
        with self._guard:
            return self._loop

    def _report(self, on_done: Callable[[Any], None] | None, result: Any) -> None:
        if on_done is not None:
            self._post(functools.partial(on_done, result))

    def _post(self, fn: Callable[[], object]) -> None:
        """Đưa `fn` về chạy trên thread Qt (gọi được từ mọi thread)."""
        try:
            self._relay.emit(fn)
        except RuntimeError:  # object Qt đã bị xóa: không còn ai nghe
            log.debug("NodeHost đã bị xóa, bỏ một thông báo")

    @Slot(object)
    def _on_relay(self, fn: Callable[[], object]) -> None:
        try:
            fn()
        except Exception:
            log.exception("lỗi trong slot của NodeHost")

    def _on_started(self, name: str, receive_dir: Path | None, receive_dir_error: Path | None) -> None:
        if self._state is _State.STARTING:
            self._state = _State.RUNNING
            self._node_name = name
            self._receive_dir = receive_dir
            self._receive_dir_error = receive_dir_error
            self.started.emit()

    def _on_start_failed(self, code: str, detail: str) -> None:
        if self._state is _State.STARTING:
            self._state = _State.STOPPING
            self.start_failed.emit(code, detail)

    def _on_finished(self) -> None:
        if self._state is not _State.STOPPED:
            self._state = _State.STOPPED
            self.stopped.emit()

    # ---- Nội bộ: thread node -------------------------------------------------------------

    def _thread_main(self) -> None:
        try:
            with asyncio.Runner() as runner:
                runner.run(self._main())
        except BaseException:
            log.exception("thread node dừng vì lỗi")
        finally:
            with self._guard:
                self._loop = None
                self._wake = None
            self._post(self._on_finished)

    async def _main(self) -> None:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(errorlog.loop_exception_handler)
        wake = asyncio.Event()
        with self._guard:
            self._loop, self._wake = loop, wake
            if self._stop_requested:
                return
        opts = self._options
        try:
            node = Node(
                opts.config_dir,
                name=opts.name,
                host=opts.host,
                port=opts.port,
                mdns=opts.mdns,
                accept_pairing=False,  # đóng mặc định; mở theo luật sau `start()`
                on_pairing_prompt=self._pairing_prompt_callback,
                on_pairing_finished=self._pairing_finished_callback,
                auto_connect=True,
                on_event=self._node_callback,
                receive_dir=opts.receive_dir,
                auto_accept=False,
                on_transfer_event=self._transfer_callback,
                save_args=opts.save_args,
                clipboard=opts.clipboard,
                on_clipboard_event=self._clipboard_callback,
            )
        except Exception as e:
            self._fail(e)
            return
        self._node = node
        start = asyncio.create_task(node.start(), name="teleport.ui.start")
        stopping = asyncio.create_task(wake.wait(), name="teleport.ui.stop")
        try:
            await asyncio.wait({start, stopping}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stopping.cancel()
        if not start.done():
            # Dừng khi đang khởi động: không hủy start; close() đánh dấu, start tự dừng ở bước kế.
            await self._close_node(node)
            done, _ = await asyncio.wait({start}, timeout=app_node.close_time_limit())
            if not done:
                start.cancel()
                await asyncio.wait({start}, timeout=_CANCEL_WAIT)
            if start.done() and not start.cancelled():
                start.exception()  # đã xử lý: không để loop báo “exception was never retrieved”
            return
        error: BaseException | None = asyncio.CancelledError() if start.cancelled() else start.exception()
        if error is not None:
            if wake.is_set():
                return  # đã có lệnh dừng: chỉ phát `stopped`
            self._fail(error)
            return
        if wake.is_set():
            await self._close_node(node)
            return
        try:
            self.apply_pairing_policy(node)  # trước `started`: máy hiện nhận ghép đôi từ đây
        except Exception as e:
            log.error("không áp được luật nhận ghép đôi: %s", type(e).__name__)
        self._serving = True
        receive_dir, receive_dir_error = self._read_receive_dir(node)
        self._post(functools.partial(self._on_started, node.name, receive_dir, receive_dir_error))
        await wake.wait()
        self._serving = False
        await self._cancel_jobs()
        await self._close_node(node)

    @staticmethod
    def _read_receive_dir(node: Node) -> tuple[Path | None, Path | None]:
        """Thread node: (thư mục nhận, thư mục đã lưu không mở được); lỗi khi đọc → (None, None)."""
        try:
            error = node.receive_dir_error
            return node.transfers.receive_dir, None if error is None else error.path
        except Exception as e:
            log.warning("không đọc được thư mục nhận của node: %s", type(e).__name__)
            return None, None

    def _fail(self, error: BaseException) -> None:
        code, detail = classify_start_error(error)
        self._post(functools.partial(self._on_start_failed, code.value, detail))

    async def _close_node(self, node: Node) -> None:
        """`node.close()` trong task riêng, không hủy trước hạn `close_time_limit()` (như CLI)."""
        closing = asyncio.create_task(node.close(), name="teleport.ui.close")
        done, _ = await asyncio.wait({closing}, timeout=app_node.close_time_limit())
        if not done:
            log.warning("đóng node quá hạn, hủy phần còn lại")
            closing.cancel()
            await asyncio.wait({closing}, timeout=_CANCEL_WAIT)
        if closing.done() and not closing.cancelled() and (error := closing.exception()) is not None:
            log.error("đóng node lỗi: %s", type(error).__name__)

    async def _cancel_jobs(self) -> None:
        jobs = [job for job in self._jobs if not job.done()]
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.wait(jobs, timeout=_SUBMIT_CANCEL_WAIT)

    def _run_call(self, fn: Callable[[Node], Any], on_done: Callable[[Any], None] | None) -> None:
        node = self._node
        result: Any
        if not self._serving or node is None:
            result = RuntimeError("node chưa chạy hoặc đang đóng")
        else:
            try:
                result = fn(node)
            except Exception as e:
                result = e
        self._report(on_done, result)

    def _run_submit(
        self,
        fn: Callable[[Node], Awaitable[Any]],
        on_done: Callable[[Any], None] | None,
        *,
        job: SubmitJob,
    ) -> None:
        node = self._node
        if not self._serving or node is None:
            self._report(on_done, RuntimeError("node chưa chạy hoặc đang đóng"))
            return
        if job._cancel_pending():  # bị hủy trước khi task kịp tạo: không chạy `fn`
            self._report(on_done, asyncio.CancelledError())
            return
        try:
            task = asyncio.ensure_future(fn(node))
        except Exception as e:
            self._report(on_done, e)
            return
        if not job._attach(task):  # lệnh hủy tới giữa hai bước trên
            task.cancel()
        self._jobs.add(task)

        def finished(task: asyncio.Future[Any]) -> None:
            self._jobs.discard(task)
            result: Any = (
                asyncio.CancelledError() if task.cancelled() else (task.exception() or task.result())
            )
            self._report(on_done, result)

        task.add_done_callback(finished)

    def _node_callback(self, event: NodeEvent) -> None:
        self._post(functools.partial(self.node_event.emit, event))

    def _transfer_callback(self, update: TransferUpdate) -> None:
        self._post(functools.partial(self.transfer_event.emit, update))

    def _clipboard_callback(self, event: ClipboardEvent) -> None:
        self._post(functools.partial(self.clipboard_event.emit, event))

    def _pairing_prompt_callback(self, prompt: PairingPrompt) -> None:
        """`on_prompt` của lõi: chỉ chuyển về thread Qt, không raise (raise → PROMPT_FAILED)."""
        try:
            self._post(functools.partial(self.pairing_prompt.emit, prompt))
        except Exception:
            log.exception("không chuyển được lời hỏi ghép đôi về thread Qt")

    def _pairing_finished_callback(self, result: PairingFinished) -> None:
        try:
            self._post(functools.partial(self.pairing_finished.emit, result))
        except Exception:
            log.exception("không chuyển được kết quả ghép đôi về thread Qt")
