"""Giao diện dòng lệnh: `teleport <lệnh>`.

Mỗi lệnh là một hàm `cmd_<tên>(args) -> int` (mã thoát).

Mã thoát: 0 thành công; 1 lỗi lúc chạy (khóa bận, danh tính/kho hỏng, không mở được
cổng, không bật được mDNS, ghép đôi không thành, không tìm thấy thiết bị); 2 cú pháp
lệnh sai (argparse, đích trông như địa chỉ mà sai dạng, `--name` không hợp lệ).

Mã thoát của truyền file:

- `send`: 0 khi lượt gửi xong (`DONE`), kể cả khi Ctrl+C tới sau đó; 1 khi lượt kết thúc khác
  `DONE`, file không gửi được (trừ thư mục), `--to` không khớp đúng một thiết bị tin cậy, khóa
  bận, không kết nối được, hay Ctrl+C trước khi xong; 2 khi `--limit-rate` / `--address` sai,
  quá `MAX_OFFER_FILES` file, chọn thư mục, hay chọn một file hai lần.
- `receive`: 0 khi dừng bằng Ctrl+C (kể cả lần hai, kể cả khi có lượt lỗi, kể cả khi có lượt
  tạm dừng); 1 khi lỗi khởi động (khóa bận, thư mục nhận không dùng được…); 2 khi tham số sai.

`send` kiểm `--to` (`find_trusted`) và các file (`preview_sources`) trước khi lấy `node.lock`
hay đụng mạng; node của nó nghe cổng 0 (không lưu), chỉ duyệt mDNS và chỉ tự nối tới đích
(`--address`: `connect_hint`, lần thử thất bại được báo ngay). Một tiến trình gửi đúng một
lượt; mất kết nối thì chờ nối lại tới `RECONNECT_GRACE`. `receive` quảng bá mDNS, giữ kết nối
với mọi thiết bị tin cậy, hỏi `[c/k]` từng `offer` theo docs/mvp.md mục 7.3 (`--yes`: tự nhận,
không đọc stdin); lượt nhận dở được khôi phục khi khởi động thì nhận tiếp, không hỏi lại.

Bẫy tín hiệu của `send` / `receive`: `cancel{user}` của `send` và `reject{user}` cho `offer` đang
chờ của `receive` chỉ ra dây trong `Node.close()` có trật tự (`begin_close` rồi `flush_control`);
lượt đang nhận thì tạm dừng, không gửi gì. Không dùng `task.cancel()` cho Ctrl+C như các lệnh khác: sau
một lần hủy, `Task.cancelling()` ≥ 1 suốt lúc `close()` chạy trong task đó, zeroconf thấy vậy thì
dừng giữa chừng; còn Ctrl+C lần hai qua handler mặc định của `asyncio.Runner` ném
KeyboardInterrupt. Vì vậy `cmd_send` / `cmd_receive` gắn handler trước `runner.run` (Runner thấy
SIGINT đã có handler thì không gắn handler riêng) và khôi phục sau khi đóng Runner: POSIX dùng
`loop.add_signal_handler` cho SIGINT, SIGTERM; Windows dùng `signal.signal` cho SIGINT, SIGBREAK
kèm `call_soon_threadsafe` (Proactor đã có wakeup fd). Handler chỉ gọi `Interrupts.press()`. Lần
đầu: in “Đang dừng…”, hủy task làm việc (task đó không sở hữu node), rồi `node.close()` chạy
trong task riêng, không bị hủy, tối đa `app.node.close_time_limit()` giây; lần hai hay hết hạn:
hủy `close()` (thoát cứng, không chờ đĩa). Ctrl+C lúc đang chờ `node.lock` có thể trễ tới
`LOCK_TIMEOUT` (khóa chờ bằng `time.sleep`).

`list` chỉ duyệt mDNS vài giây: không giữ `node.lock`, không quảng bá máy này.
Chế độ ẩn (`settings.visible`, đổi ở giao diện; CLI không có lệnh đổi): `listen`, `receive` và
`send` tôn trọng nó (không quảng bá) và in một dòng nhắc; `listen` khi ẩn vẫn nhận ghép đôi.
`listen` quảng bá và duyệt mDNS, tự giữ kết nối với các máy đã ghép đôi và in sự kiện
thiết bị. `pair <tên>` duyệt mDNS (không quảng bá, không tự kết nối) rồi chọn đúng một
máy; `pair <ip>` không dùng mDNS. mDNS bật khi nghe trên mọi địa chỉ (mặc định), hoặc
khi có cờ ẩn `--mdns-interface` (test).

`listen`, `pair`, `send` và `receive` chạy một node trong tiến trình này (tới v0.3); `listen`,
`pair` và `receive` (không `--yes`) hỏi người dùng qua stdin. stdin được đọc bằng `os.read`
trong một thread daemon, không dùng `input()`: thread bị chặn trong bộ đệm của `sys.stdin` có
thể làm Python báo “Fatal Python error” lúc thoát. Mỗi dòng mang mốc `time.perf_counter()` lúc
đọc; dòng gõ trước lúc hiện mã bị bỏ, nên gõ sẵn `c` không xác nhận được một mã chưa thấy. Dùng
`perf_counter` chứ không dùng `monotonic`: trên Windows `monotonic` chỉ chính xác tới ~15,6 ms,
nên một dòng đọc trước lúc hiện mã vài ms vẫn có thể mang cùng mốc.

Lời hỏi ghép đôi theo bố cục docs/mvp.md mục 7.2: dòng mã chỉ gồm nhãn cố định và mã, đứng
trước mọi chữ do máy kia đặt; tên máy kia (chưa xác thực) hiện qua `display_name`, trong “…”.

`pair` bị Ctrl+C khi kết quả đã có (ví dụ lúc đang đóng kết nối sau khi đã ghép đôi) thì
vẫn báo đúng kết quả đó và trả mã thoát theo nó; chỉ khi chưa có kết quả mới báo đã hủy.

`--json`: `listen`, `pair`, `send` và `receive` in JSON Lines (mỗi sự kiện một dòng), các lệnh
khác in một object. Khóa tiếng Anh, có `time` UTC. `receive` phát `restored` cho mỗi lượt nhận
dở được khôi phục còn trong hạn nối lại (thay cho `offer`; lượt quá hạn chỉ có `result: expired`),
và `result` với `result: "suspended"` cho lượt tạm dừng khi Ctrl+C; `payload_sent` (byte payload
đã gửi) chỉ có trong `result` của `send`.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime
import functools
import glob
import ipaddress
import json
import logging
import math
import ntpath
import os
import re
import shutil
import signal
import sys
import threading
import time
import unicodedata
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, TextIO

from teleport import __version__
from teleport.app import node as app_node  # close_time_limit đọc lúc dùng (test vá)
from teleport.app import sources as app_sources  # MAX_FILE_SIZE đọc lúc dùng
from teleport.app import transfers as app_transfers  # preview_sources, MIN_RATE_LIMIT đọc lúc dùng
from teleport.app.devices import (
    AmbiguousDevice,
    DeviceNotFound,
    DeviceView,
    parse_manual_address,
    resolve_device,
)
from teleport.app.node import (
    MAX_SCAN_TIMEOUT,
    SCAN_TIMEOUT,
    ConfigDirError,
    ConnectFailed,
    DeviceConnected,
    DeviceDisconnected,
    DeviceOffline,
    DeviceOnline,
    DiscoveryUnavailable,
    MdnsOptions,
    Node,
    NodeEvent,
    ReceiveDirChoice,
    ReceiveDirUnavailable,
    find_trusted,
    scan_devices,
    unpair_offline,
)
from teleport.app.pairing import PairingFinished, PairingOutcome, PairingPrompt
from teleport.app.settings import Settings
from teleport.app.storage import PathTooLongError, UnsafeReceiveDirError
from teleport.app.transfers import (
    DataUnreachable,
    Direction,
    FileDone,
    OfferReceived,
    SourceError,
    SourceErrorKind,
    TransferFinished,
    TransferInfo,
    TransferKey,
    TransferProgress,
    TransferResult,
    TransferResumed,
    TransferStatus,
    TransferStatusChanged,
    TransferUpdate,
)
from teleport.core import pairing as core_pairing  # WARN_RECENT_CODES đọc lúc dùng
from teleport.core.display import display_filename, display_name, format_duration, format_size, text_width
from teleport.core.filenames import INVISIBLE_CHARS
from teleport.core.links import ConnectResult, is_saveable
from teleport.core.messages import MAX_OFFER_FILES, MessageError, validate_device_name
from teleport.core.pairing import Role
from teleport.core.pairing_code import format_code
from teleport.lock import NodeLockedError
from teleport.net.connection import DEFAULT_PORT
from teleport.paths import ENV_HOME, config_dir, default_receive_dir
from teleport.trust.identity import IdentityError, format_fingerprint, load_or_create_identity
from teleport.trust.store import TrustedDevice, TrustStoreError

# (time.perf_counter() lúc đọc, dòng không kèm "\n"); dòng None = EOF
Lines = asyncio.Queue[tuple[float, str | None]]

_ANY_HOST = "0.0.0.0"
_MAX_QUEUED_LINES = 100  # hàng đợi stdin đầy thì bỏ dòng mới (người dùng gõ dồn)
_MAX_LINE_BYTES = 4096  # dòng dài hơn bị bỏ (không giữ trong RAM)
# Console Windows: Ctrl+C làm lần đọc stdin đang chờ trả 0 byte, trông như EOF. Chờ một
# chút trước khi báo EOF để lệnh hủy (Ctrl+C) tới trước, thay vì bị coi là “từ chối”.
_TTY_EOF_DELAY = 0.3
_YES = frozenset({"c", "co", "y", "yes"})
_NO = frozenset({"k", "khong", "n", "no"})

log = logging.getLogger(__name__)

_PAIRED = PairingOutcome.PAIRED
_UNFINISHED = frozenset(
    {
        PairingOutcome.USER_REJECTED,
        PairingOutcome.TIMEOUT,
        PairingOutcome.PEER_REJECTED,
        PairingOutcome.PEER_TIMEOUT,
        PairingOutcome.PROTOCOL_ERROR,
        PairingOutcome.PEER_INVALID,
        PairingOutcome.PEER_ABORTED,
        PairingOutcome.CONNECTION_LOST,
    }
)


def cmd_identity(args: argparse.Namespace) -> int:
    directory = args.config_dir or config_dir()
    try:
        identity = load_or_create_identity(directory)
    except OSError as e:  # ví dụ đường dẫn là một file
        _config_dir_error(_Output(sys.stdout, sys.stderr, False), directory, e)
        return 1
    port = Settings.load(directory).port or DEFAULT_PORT
    print(f"Mã thiết bị:   {identity.device_id}")
    print(f"Pin ngắn:      {identity.short_fingerprint}")
    print(f"Fingerprint:   {format_fingerprint(identity.fingerprint)}")
    print(f"Cổng:          {port}")
    print(f"Thư mục:       {directory}")
    return 0


# ---- Đầu ra --------------------------------------------------------------------------------


def _utc_now() -> str:
    """Thời điểm hiện tại dạng `YYYY-MM-DDTHH:MM:SS.mmmZ` (UTC)."""
    now = datetime.datetime.now(datetime.UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _json_line(obj: object) -> str:
    """Một dòng JSON (UTF-8, không thoát chữ thường); riêng U+2028 và U+2029 được viết thoát,
    vì nhiều bên đọc (ví dụ `str.splitlines`) coi chúng là xuống dòng và làm vỡ JSON Lines."""
    return json.dumps(obj, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _stream_isatty(stream: object) -> bool:
    try:
        return bool(stream.isatty())  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        return False


class _Output:
    """In ra `out` / `err` theo chế độ text hoặc JSON; mọi dòng đều flush ngay.

    `tty` (mặc định `out.isatty()`): dòng tiến độ được vẽ lại tại chỗ bằng CR, không dùng mã
    ANSI; in dòng text khác thì xuống dòng trước.

    Câu hỏi đang mở (`ask`, tới khi `answered` / `close_question`): dòng khác in chen vào thì câu
    hỏi được in lại ngay sau, để người dùng luôn thấy mình đang được hỏi; dòng tiến độ không vẽ.
    """

    def __init__(self, out: TextIO, err: TextIO, json_mode: bool, *, tty: bool | None = None) -> None:
        self.out = out
        self.err = err
        self.json = json_mode
        self.tty = _stream_isatty(out) if tty is None else tty
        self._line_open = False  # vừa in “[c/k]: ” và chưa xuống dòng
        self._question: str | None = None  # câu hỏi đang mở (chưa trả lời, chưa đóng)
        self._progress_width = 0  # TTY: số cột của dòng tiến độ đang vẽ (chưa xuống dòng); 0 = không có

    def text(self, *lines: str) -> None:
        """Dòng cho người đọc (chỉ ở chế độ text)."""
        if self.json:
            return
        self._close_line()
        for line in lines:
            print(line, file=self.out, flush=True)
        self._reask()

    def ask(self, question: str) -> None:
        """In câu hỏi, để con trỏ ở cuối dòng; câu hỏi mở tới khi `answered` / `close_question`."""
        if self.json:
            return
        self._close_line()
        self._question = question
        self._reask()

    def answered(self) -> None:
        """Người dùng đã gõ Enter: terminal đã xuống dòng, câu hỏi đóng (hỏi lại thì `ask` lần nữa)."""
        self._line_open = False
        self._question = None

    def close_question(self) -> None:
        """Câu hỏi đóng mà không có câu trả lời (máy kia hủy, đầu vào đóng, đang dừng…)."""
        self._question = None

    def _reask(self) -> None:
        if self._question is not None:
            print(self._question, end="", file=self.out, flush=True)
            self._line_open = True

    def progress(self, line: str) -> None:
        """Dòng tiến độ (chỉ ở chế độ text).

        TTY: vẽ lại dòng hiện tại bằng CR, đệm khoảng trắng tới độ dài dòng trước; không vẽ khi
        đang có lời hỏi mở. Không TTY: in như một dòng thường.
        """
        if self.json:
            return
        if not self.tty:
            self.text(line)
            return
        if self._question is not None or self._line_open:
            return  # đang hỏi: không vẽ đè lên lời hỏi
        width = text_width(line)
        pad = " " * max(0, self._progress_width - width)
        print("\r" + line + pad, end="", file=self.out, flush=True)
        self._progress_width = max(width, 1)

    def event(self, kind: str, /, **fields: Any) -> None:
        """Một dòng JSON (chỉ ở chế độ `--json`)."""
        if not self.json:
            return
        obj = {"event": kind, "time": _utc_now(), **fields}
        print(_json_line(obj), file=self.out, flush=True)

    def error(self, code: str, message: str, *, extra: Sequence[str] = (), **fields: Any) -> None:
        """Lỗi: text → “Lỗi: …” ra `err`; JSON → object `error` ra `out`."""
        if self.json:
            self.event("error", error=code, message=message, **fields)
            return
        self._close_line()
        print(f"Lỗi: {message}", file=self.err, flush=True)
        for line in extra:
            print(line, file=self.err, flush=True)
        self._reask()

    def _close_line(self) -> None:
        if self._line_open or self._progress_width:
            print(file=self.out, flush=True)
            self._line_open = False
            self._progress_width = 0


def _target(result: PairingFinished) -> str:
    return result.address if result.port is None else f"{result.address}:{result.port}"


def outcome_message(result: PairingFinished, *, seen_name: str | None = None) -> list[str]:
    """Câu báo kết quả ghép đôi (docs/mvp.md mục 8); dòng đầu là câu chính.

    `seen_name`: tên của đích thấy qua mDNS (`pair <tên>`); khi có, “không kết nối được”
    đổi thành câu “Thấy X nhưng không kết nối được…”.

    Đã ghép đôi: dùng tên vừa lưu (`device.name`, tên máy kia gửi trong `hello`, ở cả hai
    vai, kể cả khi ghép đôi lại). Phiên chưa xong mà chưa hiện mã
    (`code_shown` False) thì không nhắc so mã, câu theo vai. Danh tính khác ở vai trả lời:
    `pair_request` chưa được xác minh nên không gợi ý hủy ghép đôi máy thật.
    """
    outcome = result.outcome
    target = _target(result)
    peer = result.peer_name or seen_name
    x = _name_label(peer) if peer else target
    responder = result.role is Role.RESPONDER
    if outcome is PairingOutcome.UNREACHABLE and seen_name is not None:
        return [_unreachable_seen(_name_label(seen_name)), _HOTSPOT_HINT]
    if outcome is _PAIRED:
        name = _name_label(result.device.name) if result.device is not None else x
        return [f"Đã ghép đôi với {name}."]
    if outcome in _UNFINISHED:
        if result.code_shown:
            return [
                f"Ghép đôi với {x} chưa xong. Nếu mã trên hai máy khác nhau, có thể có người đang giả mạo."
            ]
        if responder:
            return [f"Một máy tự xưng là {x} đã yêu cầu ghép đôi nhưng phiên dừng trước khi hiện mã."]
        return [f"Ghép đôi với {x} chưa xong vì phiên dừng trước khi hiện mã. Hãy thử lại."]
    if outcome is PairingOutcome.IDENTITY_CONFLICT:
        known = _name_label(result.known_name) if result.known_name else x
        if responder:
            return [
                f"Một máy chưa xác minh tự xưng là {known} nhưng dùng danh tính khác với lúc ghép đôi. "
                "Có thể có người đang giả mạo máy đó. Yêu cầu ghép đôi đã bị chặn."
            ]
        short_id = (result.peer_device_id or "")[:8]
        return [
            f"{known} đang dùng một danh tính khác với lúc ghép đôi. Có thể có người đang giả mạo máy này. "
            "Kết nối đã bị chặn.",
            "Nếu chắc chắn máy đó đã đổi danh tính, hãy hủy ghép đôi mục cũ trước: "
            f"`teleport unpair {short_id}`",
        ]
    if outcome in (PairingOutcome.PEER_BUSY, PairingOutcome.REJECTED):
        return [
            f"{x} chưa sẵn sàng ghép đôi: máy đó đang ẩn, đang ghép đôi với máy khác, "
            "chưa mở chế độ chờ ghép đôi, hoặc cần chờ một lát sau lần thử trước. Hãy thử lại sau.",
            "Trên máy đó, hãy chạy: `teleport listen`",
        ]
    if outcome is PairingOutcome.UNREACHABLE:
        return [
            f"Không kết nối được tới {target}. Hãy kiểm tra Teleport đang chạy trên máy đó, "
            "hai máy dùng chung một mạng, và tường lửa cho phép Teleport."
        ]
    if outcome is PairingOutcome.IDENTITY_MISMATCH:
        return [
            f"Thiết bị ở {target} gửi danh tính không hợp lệ nên kết nối đã bị chặn. "
            "Có thể có người đang giả mạo."
        ]
    if outcome is PairingOutcome.VERSION_MISMATCH:
        return [f"{target} đang dùng phiên bản Teleport khác. Hãy cập nhật cả hai máy lên cùng phiên bản."]
    if outcome is PairingOutcome.SELF:
        return ["Đó là chính máy này. Hãy nhập địa chỉ của máy kia."]
    if outcome is PairingOutcome.BUSY:
        return ["Máy này đang có một phiên ghép đôi khác. Hãy thử lại sau."]
    if outcome is PairingOutcome.SAVE_FAILED:
        return [
            f"Đã xác nhận ghép đôi với {x} nhưng không lưu được vào trusted.json. "
            "Hãy kiểm tra quyền ghi thư mục cấu hình rồi ghép đôi lại."
        ]
    if outcome is PairingOutcome.PROMPT_FAILED:
        return ["Không hiện được mã ghép đôi trên máy này nên đã hủy ghép đôi. Hãy thử lại."]
    return ["Đã hủy ghép đôi."]  # CANCELLED


def _unreachable_seen(name: str) -> str:
    return (
        f"Thấy {name} nhưng không kết nối được. Mạng Wi-Fi này có thể đang chặn các thiết bị nói chuyện "
        "với nhau (hay gặp ở quán cà phê, khách sạn)."
    )


_HOTSPOT_HINT = (
    "Hãy thử dùng điểm phát Wi-Fi từ điện thoại, và kiểm tra tường lửa trên máy kia đã cho phép Teleport."
)
_OS_LABELS = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}


def _os_label(os_name: str | None) -> str:
    if os_name is None:
        return "?"
    return _OS_LABELS.get(os_name, os_name)


def _paired_label(view: DeviceView) -> str:
    return "đã ghép đôi" if view.paired else "chưa ghép đôi"


def _view_dict(view: DeviceView) -> dict[str, Any]:
    return {
        "device_id": view.device_id,
        "name": view.name,
        "os": view.os,
        "paired": view.paired,
        "online": view.online,
        "addresses": list(view.addresses),
        "port": view.port,
    }


def connect_failed_message(view: DeviceView, result: ConnectResult) -> list[str]:
    """Câu báo không kết nối được tới thiết bị đã ghép đôi (docs/mvp.md mục 8)."""
    x = _name_label(view.name)
    short_id = view.device_id[:8]
    if result is ConnectResult.REJECTED:
        return [
            f"{x} từ chối kết nối từ máy này. Có thể máy đó đã hủy ghép đôi.",
            f"Để ghép đôi lại: `teleport pair {short_id}`",
        ]
    if result is ConnectResult.IDENTITY_MISMATCH:
        return [
            f"{x} đang dùng một danh tính khác với lúc ghép đôi. Có thể có người đang giả mạo máy này. "
            "Kết nối đã bị chặn.",
            "Nếu chắc chắn máy đó đã đổi danh tính, hãy hủy ghép đôi mục cũ trước: "
            f"`teleport unpair {short_id}`",
        ]
    if result is ConnectResult.VERSION_MISMATCH:
        return [f"{x} đang dùng phiên bản Teleport khác. Hãy cập nhật cả hai máy lên cùng phiên bản."]
    return [_unreachable_seen(x)]


def _print_event(output: _Output, event: NodeEvent) -> None:
    """In một `NodeEvent` của `teleport listen`."""
    view = event.device
    who = f"“{_name_label(view.name)}” ({view.device_id[:8]}"
    if isinstance(event, DeviceOnline):
        where = f"{view.addresses[0]}:{view.port}" if view.addresses else "?"
        output.text(f"Thấy {who}, {_os_label(view.os)}, {_paired_label(view)}) tại {where}.")
        output.event(
            "device_online",
            device_id=view.device_id,
            name=view.name,
            os=view.os,
            paired=view.paired,
            addresses=list(view.addresses),
            port=view.port,
        )
    elif isinstance(event, DeviceOffline):
        output.text(f"{who}) đã rời mạng.")
        output.event("device_offline", device_id=view.device_id, name=view.name)
    elif isinstance(event, DeviceConnected):
        output.text(f"Đã kết nối với {who}).")
        output.event("device_connected", device_id=view.device_id, name=view.name, outgoing=event.outgoing)
    elif isinstance(event, DeviceDisconnected):
        output.text(f"Mất kết nối với {who})." + (" Đang nối lại…" if view.online else ""))
        output.event("device_disconnected", device_id=view.device_id, name=view.name)
    elif isinstance(event, ConnectFailed):
        lines = connect_failed_message(view, event.result)
        output.text(*lines)
        output.event(
            "connect_failed",
            device_id=view.device_id,
            name=view.name,
            result=event.result.value,
            message=" ".join(lines),
        )


def _emit_result(output: _Output, result: PairingFinished, *, seen_name: str | None = None) -> None:
    lines = outcome_message(result, seen_name=seen_name)
    output.text(*lines)
    output.event(
        "pair_result",
        session_id=result.session_id,
        role=result.role.value,
        outcome=result.outcome.value,
        peer_name=result.peer_name,
        peer_device_id=result.peer_device_id,
        address=result.address,
        message=" ".join(lines),
    )


# ---- Hỏi người dùng ------------------------------------------------------------------------


def _code_warning(prompt: PairingPrompt) -> str | None:
    """Cảnh báo khi máy này (vai trả lời) đã hiện nhiều mã trong 1 phút (docs/mvp.md mục 8)."""
    if prompt.role is not Role.RESPONDER or prompt.recent_codes < core_pairing.WARN_RECENT_CODES:
        return None
    return (
        f"Cảnh báo: máy này đã hiện {prompt.recent_codes} mã ghép đôi trong 1 phút qua. "
        "Nếu bạn không tự ghép đôi nhiều lần như vậy, có thể có người đang thử giả mạo: "
        "hãy từ chối (gõ k)."
    )


# Dòng đầu của lời hỏi xét theo lệnh (mvp mục 7.2); không chứa chữ số hay chữ do máy kia đặt.
_PROMPT_HEADER_LISTEN = "Có yêu cầu ghép đôi. Hãy so mã dưới đây với mã trên màn hình máy kia."
_PROMPT_HEADER_PAIR = "Hãy so mã dưới đây với mã trên màn hình máy kia."


def _prompt_lines(prompt: PairingPrompt, *, listening: bool) -> list[str]:
    """Các dòng của lời hỏi ghép đôi trước câu “Trùng khớp?” (mvp mục 7.2).

    Thứ tự bắt buộc: tiêu đề cố định, dòng mã (chỉ nhãn và mã), cảnh báo số mã (nếu có),
    tên máy kia tự xưng, tên đã lưu (nếu đã ghép đôi), tên mới (nếu ghép đôi lại sẽ đổi tên).
    Tên chỉ hiện qua `display_name`, trong “…”, sau dòng mã: kẻ đứng giữa đặt tên trông
    như mã cũng không chen được lên trước.
    """
    short_id = prompt.peer_device_id[:8]
    lines = [
        _PROMPT_HEADER_LISTEN if listening else _PROMPT_HEADER_PAIR,
        f"Mã ghép đôi:   {format_code(prompt.code)}",
    ]
    warning = _code_warning(prompt)
    if warning is not None:
        lines.append(warning)
    name = _name_label(prompt.peer_name)
    lines.append(f"Máy kia tự xưng là “{name}” (mã máy {short_id}, {prompt.address}).")
    if prompt.known_name is not None:
        known = _name_label(prompt.known_name)
        lines.append(f"Máy này đã ghép đôi với mã máy {short_id} trước đây, tên đã lưu: “{known}”.")
        # Ghép đôi lại cập nhật tên theo hello ở cả hai vai (protocol mục 5.5).
        if prompt.known_name != prompt.peer_name:
            lines.append(f"Ghép đôi xong, tên sẽ đổi thành “{name}”.")
    return lines


@dataclass
class _PairState:
    """Kết quả của `pair`, ghi ngay khi có để `cmd_pair` vẫn báo đúng khi bị Ctrl+C giữa chừng."""

    result: PairingFinished | None = None  # kết quả cuối, ghi trước mọi `await` sau khi có
    seen_name: str | None = None  # `pair <tên>`: tên thấy qua mDNS (câu “Thấy X nhưng…”)
    emitted: bool = False  # đã in kết quả: cmd_pair không in thêm


class _Prompter:
    """Hiện lời hỏi ghép đôi và chuyển câu trả lời từ stdin tới `PairingService.decide`."""

    def __init__(self, output: _Output, *, listening: bool, state: _PairState | None = None) -> None:
        self._output = output
        self._listening = listening  # listen: in mọi kết quả; pair: run_pair tự in kết quả
        self._state = state  # pair: ghi kết quả ngay trong on_finished
        self.node: Node | None = None
        self._prompt: PairingPrompt | None = None
        self._shown_at = 0.0
        self._stdin_closed = False
        self._told_closed = False  # đã in `_PAIR_STDIN_CLOSED` (chỉ in một lần)
        self.stopping = False  # listen: node đang đóng (Ctrl+C), không mời chờ tiếp

    def on_prompt(self, prompt: PairingPrompt) -> None:
        self._prompt = prompt
        self._shown_at = time.perf_counter()  # cùng đồng hồ với mốc của StdinReader
        out = self._output
        out.text(*_prompt_lines(prompt, listening=self._listening))
        out.ask("Trùng khớp? [c/k]: ")
        # JSON giữ nguyên tên gốc: giao diện đọc JSON tự hiện theo mvp mục 7.2.
        out.event(
            "pair_prompt",
            session_id=prompt.session_id,
            role=prompt.role.value,
            peer_name=prompt.peer_name,
            peer_device_id=prompt.peer_device_id,
            address=prompt.address,
            code=prompt.code,
            expires_in=round(max(0.0, prompt.expires_at - asyncio.get_running_loop().time()), 3),
            recent_codes=prompt.recent_codes,
            warning=_code_warning(prompt),
            known_name=prompt.known_name,
        )
        if self._stdin_closed:
            self._reject_closed()

    def on_finished(self, result: PairingFinished) -> None:
        if self._prompt is not None and self._prompt.session_id == result.session_id:
            self._prompt = None  # lời hỏi tự hủy (hết giờ, máy kia hủy…)
            self._output.close_question()
        if self._state is not None and not self._state.emitted:
            self._state.result = result
        if not self._listening:
            return
        _emit_result(self._output, result)
        if not self.stopping and result.outcome is not PairingOutcome.CANCELLED:
            self._output.text("Tiếp tục chờ ghép đôi… (Ctrl+C để dừng)")

    def feed(self, read_at: float, line: str | None) -> None:
        """Một dòng từ stdin (`None` = EOF)."""
        if line is None:
            self._stdin_closed = True
            if self._prompt is not None:
                self._reject_closed()
            return
        if self._prompt is None or read_at < self._shown_at:
            return  # không có lời hỏi, hoặc dòng gõ trước lúc hiện mã
        self._output.answered()
        answer = line.strip().casefold()
        if answer.isascii() and answer in _YES:
            if self._decide(True):
                self._output.text("Đang chờ máy kia xác nhận…")
        elif answer.isascii() and answer in _NO:
            self._decide(False)
        else:
            self._output.text("Hãy gõ c (trùng) hoặc k (không trùng).")
            self._output.ask("Trùng khớp? [c/k]: ")

    def _reject_closed(self) -> None:
        """stdin đã đóng: từ chối lời hỏi đang mở; lần đầu in lý do (giống `receive`)."""
        self._output.close_question()
        if not self._told_closed:
            self._told_closed = True
            self._output.text(_PAIR_STDIN_CLOSED)
        self._decide(False)

    def _decide(self, accepted: bool) -> bool:
        prompt, self._prompt = self._prompt, None
        self._output.close_question()
        if prompt is None or self.node is None:
            return False
        return self.node.pairing.decide(prompt.session_id, accepted)


async def _feed_lines(lines: Lines, prompter: _Prompter) -> None:
    while True:
        read_at, line = await lines.get()
        prompter.feed(read_at, line)


# ---- Khởi động node ------------------------------------------------------------------------


def _config(args: argparse.Namespace) -> Path:
    return getattr(args, "config_dir", None) or config_dir()


def _valid_host(host: object) -> bool:
    if not isinstance(host, str):
        return False
    try:
        return str(ipaddress.IPv4Address(host)) == host
    except ValueError:
        return False


def _mdns_options(args: argparse.Namespace, *, advertise: bool) -> MdnsOptions | None:
    """Luật bật mDNS: có `--mdns-interface`, hoặc nghe trên mọi địa chỉ (`--host` mặc định)."""
    interfaces = getattr(args, "mdns_interface", None)
    if interfaces:
        advertised = tuple(getattr(args, "advertise_address", None) or ()) or None
        return MdnsOptions(advertise=advertise, interfaces=tuple(interfaces), advertise_addresses=advertised)
    if getattr(args, "host", _ANY_HOST) == _ANY_HOST:
        return MdnsOptions(advertise=advertise)
    return None


def _make_node(
    args: argparse.Namespace,
    output: _Output,
    prompter: _Prompter,
    *,
    accept_pairing: bool,
    mdns: MdnsOptions | None = None,
    auto_connect: bool = True,
    on_event: Callable[[NodeEvent], None] | None = None,
) -> Node | int:
    """Tạo `Node` từ tham số dòng lệnh; tham số sai → mã thoát 2 (đã in lỗi)."""
    host = getattr(args, "host", _ANY_HOST)
    if not _valid_host(host):
        output.error("invalid_address", f"Địa chỉ lắng nghe không hợp lệ: {host!r}")
        return 2
    try:
        node = Node(
            _config(args),
            name=getattr(args, "name", None),
            port=getattr(args, "port", None),
            host=host,
            accept_pairing=accept_pairing,
            on_pairing_prompt=prompter.on_prompt,
            on_pairing_finished=prompter.on_finished,
            mdns=mdns,
            auto_connect=auto_connect,
            on_event=on_event,
        )
    except MessageError as e:
        output.error("invalid_name", f"Tên thiết bị không hợp lệ: {e}")
        return 2
    except ValueError as e:
        output.error("invalid_address", f"Cổng không hợp lệ: {e}")
        return 2
    prompter.node = node
    return node


async def _start(node: Node, output: _Output) -> int | None:
    """`node.start()`; lỗi → in lỗi, trả mã thoát. Thành công → None."""
    try:
        await node.start()
    except NodeLockedError:
        output.error("node_locked", "Teleport đang chạy với thư mục cấu hình này.", extra=[_NODE_LOCKED_HINT])
        return 1
    except IdentityError as e:
        output.error("identity_error", str(e))
        return 1
    except TrustStoreError as e:
        output.error("trust_store_error", str(e))
        return 1
    except ConfigDirError as e:
        _config_dir_error(output, e.path, e.error)
        return 1
    except OSError as e:  # Node.start: OSError còn lại chỉ đến từ cổng lắng nghe
        output.error("port_unavailable", f"Không mở được cổng để lắng nghe: {e}")
        return 1
    return None


def _config_dir_error(output: _Output, path: Path, error: OSError) -> None:
    output.error("config_dir_error", f"Không dùng được thư mục cấu hình {path}: {error}")


# ---- listen --------------------------------------------------------------------------------


class _EventPrinter:
    """In `NodeEvent` của `listen`; giữ lại các sự kiện tới trước khi in xong phần đầu."""

    def __init__(self, output: _Output) -> None:
        self._output = output
        self._pending: list[NodeEvent] | None = []

    def __call__(self, event: NodeEvent) -> None:
        if self._pending is not None:
            self._pending.append(event)
        else:
            _print_event(self._output, event)

    def ready(self) -> None:
        pending, self._pending = self._pending, None
        for event in pending or ():
            _print_event(self._output, event)


def _error_text(error: BaseException) -> str:
    return str(error) or type(error).__name__


async def run_listen(args: argparse.Namespace, lines: Lines, out: TextIO, err: TextIO) -> int:
    """`teleport listen`: chờ ghép đôi tới khi bị hủy; chỉ trả về khi lỗi khởi động."""
    output = _Output(out, err, bool(getattr(args, "json", False)))
    prompter = _Prompter(output, listening=True)
    printer = _EventPrinter(output)
    mdns = _mdns_options(args, advertise=True)
    node = _make_node(
        args, output, prompter, accept_pairing=True, mdns=mdns, auto_connect=True, on_event=printer
    )
    if isinstance(node, int):
        return node
    code = await _start(node, output)
    if code is not None:
        return code
    try:
        addresses = await node.local_addresses()
        port = node.port
        assert port is not None
        discovery_error = node.discovery_error
        output.event(
            "listening",
            name=node.name,
            device_id=node.identity.device_id,
            port=port,
            addresses=list(addresses),
            discovery=node.discovery_active,
            discovery_error=None if discovery_error is None else _error_text(discovery_error),
            visible=node.visible,
        )
        suffix = "" if port == DEFAULT_PORT else f":{port}"
        target = f"{addresses[0]}{suffix}" if addresses else f"<địa chỉ IP của máy này>{suffix}"
        discovery_lines: list[str] = []
        if not node.visible:
            discovery_lines.append(_HIDDEN_LISTEN)
        elif mdns is not None and discovery_error is None:
            discovery_lines.append(
                "Máy khác trong mạng thấy máy này qua `teleport list` và tự kết nối nếu đã ghép đôi."
            )
        if mdns is not None and discovery_error is not None:
            discovery_lines.append(
                f"Cảnh báo: chưa quảng bá được qua mDNS ({_error_text(discovery_error)}); "
                "máy khác vẫn ghép đôi được bằng IP."
            )
        output.text(
            "Teleport đang chờ ghép đôi.",
            f"  Tên:      {node.name}",
            f"  Mã máy:   {node.identity.device_id[:8]}",
            f"  Cổng:     {port}",
            f"  Địa chỉ:  {', '.join(addresses) if addresses else '(không tìm thấy địa chỉ IPv4 nào)'}",
            f"Trên máy kia, chạy: teleport pair {target}",
            *discovery_lines,
            "Nhấn Ctrl+C để dừng.",
        )
        printer.ready()
        await _feed_lines(lines, prompter)
        return 0  # không tới đây: _feed_lines chạy tới khi bị hủy
    finally:
        prompter.stopping = True
        await node.close()


# ---- pair ----------------------------------------------------------------------------------

_PAIR_BROWSE_TIMEOUT = 3.0  # giây duyệt mDNS trước khi chọn thiết bị theo tên (đọc lúc dùng)
_BROWSE_POLL = 0.05
# Chuỗi “trông như địa chỉ”: chỉ gồm ký tự của IPv4/IPv6 và có “:”, hoặc chỉ gồm số và “.”.
_ADDRESS_LIKE_RE = re.compile(r"[0-9a-fA-F.:\[\]]*:[0-9a-fA-F.:\[\]]*")
_DOTTED_LIKE_RE = re.compile(r"[0-9.]*\.[0-9.]*")
_FULL_ID_RE = re.compile(r"[0-9a-f]{32}")
_IP_HINT = "teleport pair <ip[:cổng]>"
# Chế độ ẩn (mvp F10): `listen` in nguyên câu của màn hình “Chờ ghép đôi”; `receive`, `send` in dòng cảnh báo.
_HIDDEN_LISTEN = "Máy này đang ẩn nên máy kia không tự thấy. Hãy nhập IP của máy này ở máy kia."
_HIDDEN_WARNING = (
    "Cảnh báo: máy này đang ẩn (đã tắt “Cho máy chưa ghép đôi thấy máy này” trong cài đặt) nên không "
    "quảng bá trong mạng; máy đã ghép đôi tự kết nối được với máy này khi máy kia đang hiện, hoặc khi hai "
    "máy đã từng kết nối và địa chỉ không đổi."
)
_PAIR_USAGE = "teleport pair <tên | tiền tố mã | ip[:cổng]>"


def _bad_address_message(target: str) -> str:
    return (
        f"“{target}” không phải địa chỉ IPv4 hợp lệ. Hãy nhập địa chỉ IP, ví dụ 192.168.1.5 hoặc "
        "192.168.1.5:47474, hoặc tên / mã thiết bị như `teleport list` hiện."
    )


def _looks_like_address(text: str) -> bool:
    return _ADDRESS_LIKE_RE.fullmatch(text) is not None or _DOTTED_LIKE_RE.fullmatch(text) is not None


def _pair_target(text: str) -> tuple[str, tuple[str, int] | None]:
    """Phân loại đích của `pair`: trả `(đích đã bỏ khoảng trắng hai đầu, (ip, cổng) hoặc None)`.

    None nghĩa là tìm theo tên. Khoảng trắng hai đầu (cả Unicode, như NBSP khi dán từ
    web) bị bỏ. Không còn khoảng trắng bên trong: trông như địa chỉ (chỉ gồm ký tự của
    IPv4/IPv6 và có “:”, hoặc chỉ gồm số và “.”) thì là địa chỉ, không phải IPv4[:cổng]
    hợp lệ → ValueError. Có khoảng trắng bên trong: chỉ là địa chỉ khi bỏ hết khoảng
    trắng ra được IPv4[:cổng] hợp lệ (“1.2.3.4 :47474”), ngược lại là tên (“PC Nha”).
    """
    target = text.strip()
    compact = "".join(target.split())
    if compact == target:
        if not _looks_like_address(target):
            return target, None
        return target, parse_manual_address(target)
    try:
        return target, parse_manual_address(compact)
    except ValueError:
        return target, None


async def run_pair(
    args: argparse.Namespace, lines: Lines, out: TextIO, err: TextIO, *, state: _PairState | None = None
) -> int:
    """`teleport pair <tên | tiền tố mã | ip[:cổng]>`: ghép đôi với một máy; 0 nếu đã ghép đôi, ngược lại 1.

    Đích rỗng (sau khi bỏ khoảng trắng hai đầu) → mã 2. Địa chỉ hay tên: xem
    `_pair_target`; trông như địa chỉ mà không phải IPv4 hợp lệ → mã 2, không đem đi
    tìm theo tên.

    `state` (của `cmd_pair`) nhận kết quả ngay khi có, tên thấy qua mDNS và việc đã in kết
    quả hay chưa, để lệnh bị hủy giữa chừng vẫn báo đúng kết quả đã có.
    """
    if state is None:
        state = _PairState()
    output = _Output(out, err, bool(getattr(args, "json", False)))
    target = args.address.strip()
    if not target:
        output.error("invalid_address", f"Hãy nhập tên, mã thiết bị hoặc địa chỉ IP: {_PAIR_USAGE}")
        return 2
    try:
        target, endpoint = _pair_target(target)
    except ValueError:
        output.error("invalid_address", _bad_address_message(target))
        return 2
    if endpoint is not None:
        return await _pair_by_address(args, lines, output, *endpoint, state=state)
    return await _pair_by_name(args, lines, output, target, state=state)


async def _pair_by_address(
    args: argparse.Namespace, lines: Lines, output: _Output, ip: str, port: int, *, state: _PairState
) -> int:
    prompter = _Prompter(output, listening=False, state=state)
    node = _make_node(args, output, prompter, accept_pairing=False)
    if isinstance(node, int):
        return node
    code = await _start(node, output)
    if code is not None:
        return code
    try:
        output.text(f"Đang kết nối tới {ip}:{port}…")
        result = await _pair_with(node, lines, prompter, [ip], port, state=state)
        _emit_result(output, result)
        state.emitted = True
        return 0 if result.outcome is _PAIRED else 1
    finally:
        await node.close()


async def _pair_with(
    node: Node,
    lines: Lines,
    prompter: _Prompter,
    addresses: Sequence[str],
    port: int,
    *,
    state: _PairState,
) -> PairingFinished:
    """`PairingService.pair_with` kèm đọc stdin; ghi kết quả vào `state` trước mọi `await` dọn dẹp.

    `pair_with` bị hủy sau khi hai bên đã xác nhận thì vẫn trả kết quả thật (không ném).
    """
    feeder = asyncio.create_task(_feed_lines(lines, prompter), name="teleport.cli.stdin")
    try:
        result = await node.pairing.pair_with(addresses, port)
        state.result = result
        return result
    finally:
        feeder.cancel()
        await asyncio.wait({feeder})


async def _pair_by_name(
    args: argparse.Namespace, lines: Lines, output: _Output, query: str, *, state: _PairState
) -> int:
    """`pair <tên | tiền tố mã>`: duyệt mDNS (không quảng bá, không tự nối), chọn đúng một máy."""
    prompter = _Prompter(output, listening=False, state=state)
    mdns = _mdns_options(args, advertise=False)
    node = _make_node(args, output, prompter, accept_pairing=False, mdns=mdns, auto_connect=False)
    if isinstance(node, int):
        return node
    if mdns is None:
        output.error(
            "discovery_error",
            f"Không tìm được thiết bị theo tên vì khám phá mDNS đang tắt. Hãy nhập địa chỉ IP: {_IP_HINT}",
        )
        return 1
    code = await _start(node, output)
    if code is not None:
        return code
    try:
        output.text(f"Đang tìm “{query}” trong mạng…")
        if not node.discovery_active:
            reason = node.discovery_error
            why = "" if reason is None else f" ({_error_text(reason)})"
            output.error(
                "discovery_error",
                f"Không tìm được thiết bị theo tên vì không bật được khám phá mDNS{why}. "
                f"Hãy nhập địa chỉ IP: {_IP_HINT}",
            )
            return 1
        await _browse(node, query)
        view = _choose_device(output, query, node.devices())
        if view is None:
            return 1
        assert view.port is not None and view.addresses
        state.seen_name = view.name
        output.text(
            f"Đang kết nối tới “{_name_label(view.name)}” ({view.device_id[:8]}) "
            f"tại {view.addresses[0]}:{view.port}…"
        )
        result = await _pair_with(node, lines, prompter, view.addresses, view.port, state=state)
        _emit_result(output, result, seen_name=view.name)
        state.emitted = True
        return 0 if result.outcome is _PAIRED else 1
    finally:
        await node.close()


async def _browse(node: Node, query: str) -> None:
    """Chờ đủ `_PAIR_BROWSE_TIMEOUT`; chỉ dừng sớm khi `query` là mã đủ 32 ký tự và đã thấy máy đó."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _PAIR_BROWSE_TIMEOUT
    full_id = query.strip().lower()
    exact = _FULL_ID_RE.fullmatch(full_id) is not None
    while (left := deadline - loop.time()) > 0:
        if exact and any(v.device_id == full_id and v.online for v in node.devices()):
            return
        await asyncio.sleep(min(left, _BROWSE_POLL))


def _choose_device(output: _Output, query: str, views: tuple[DeviceView, ...]) -> DeviceView | None:
    """Chọn đúng một thiết bị đang thấy; không được thì in lỗi và trả None."""
    try:
        view = resolve_device(query, views)
    except DeviceNotFound:
        online = [v for v in views if v.online]
        if online:
            extra = ["Thiết bị đang thấy:", *(f"  {v.device_id[:8]}  {_name_label(v.name)}" for v in online)]
        else:
            extra = ["(chưa thấy thiết bị nào)"]
        output.error(
            "not_found",
            f"Không thấy thiết bị nào khớp “{query}” trong mạng.",
            extra=[*extra, f"Nếu mạng chặn mDNS, hãy nhập địa chỉ IP: {_IP_HINT}"],
            candidates=_candidates(tuple(online)),
        )
        return None
    except AmbiguousDevice as e:
        output.error(
            "ambiguous",
            f"“{query}” khớp nhiều thiết bị; hãy nhập mã thiết bị dài hơn:",
            extra=[f"  {d.device_id}  {_name_label(d.name)}" for d in e.candidates],
            candidates=_candidates(e.candidates),
        )
        return None
    if not view.online or not view.addresses or view.port is None:
        output.error(
            "offline",
            f"“{_name_label(view.name)}” ({view.device_id[:8]}) không có trong mạng lúc này. "
            f"Nếu mạng chặn mDNS, hãy nhập địa chỉ IP: {_IP_HINT}",
            device_id=view.device_id,
            name=view.name,
        )
        return None
    return view


# ---- list ----------------------------------------------------------------------------------


async def run_list(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    """`teleport list`: duyệt mDNS vài giây rồi in các thiết bị; không giữ `node.lock`, không quảng bá."""
    output = _Output(out, err, bool(getattr(args, "json", False)))
    directory = _config(args)
    interfaces = getattr(args, "mdns_interface", None)
    mdns = MdnsOptions(advertise=False, interfaces=tuple(interfaces)) if interfaces else None
    timeout = getattr(args, "timeout", None) or SCAN_TIMEOUT
    try:
        result = await scan_devices(directory, timeout=timeout, mdns=mdns)
    except IdentityError as e:
        output.error("identity_error", str(e))
        return 1
    except TrustStoreError as e:
        output.error("trust_store_error", str(e))
        return 1
    except ConfigDirError as e:
        _config_dir_error(output, e.path, e.error)
        return 1
    except DiscoveryUnavailable as e:
        cause = e.__cause__ if e.__cause__ is not None else e
        output.error("discovery_error", f"Không bật được khám phá mDNS ({_error_text(cause)}).")
        return 1
    if output.json:
        obj = {
            "time": _utc_now(),
            "self": {"device_id": result.device_id, "name": result.name, "port": result.port},
            "devices": [_view_dict(v) for v in result.devices],
        }
        print(json.dumps(obj, ensure_ascii=False), file=out, flush=True)
        return 0
    online = [v for v in result.devices if v.online]
    offline_paired = [v for v in result.devices if v.paired and not v.online]
    text = [f"Máy này: {_name_label(result.name)} ({result.device_id[:8]}), cổng {result.port}"]
    if online:
        text.append("Thiết bị trong mạng:")
        for v in online:
            where = ", ".join(f"{ip}:{v.port}" for ip in v.addresses)
            text.append(
                f"  {_name_label(v.name)}  {v.device_id[:8]}  {_os_label(v.os)}  {_paired_label(v)}  {where}"
            )
    else:
        text.append(_NO_DEVICES)
    if offline_paired:
        text.append("Thiết bị đã ghép đôi nhưng không thấy trong mạng:")
        text.extend(f"  {_name_label(v.name)}  {v.device_id[:8]}" for v in offline_paired)
    # Gợi ý cài lại (mvp F3): máy chưa ghép đôi trùng tên với một máy đã ghép đôi đang offline.
    offline_names = {_fold(v.name) for v in offline_paired}
    hinted: set[str] = set()
    for v in online:
        key = _fold(v.name)
        if not v.paired and key in offline_names and key not in hinted:
            hinted.add(key)
            text.append(
                f"Có một {_name_label(v.name)} mới chưa ghép đôi. "
                "Nếu máy đó vừa cài lại Teleport, hãy ghép đôi lại."
            )
    output.text(*text)
    return 0


_NO_DEVICES = (
    "Chưa thấy thiết bị nào. Hãy mở Teleport trên máy kia và kiểm tra hai máy dùng chung một mạng Wi-Fi."
)


def _fold(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


# ---- Chạy lệnh async -----------------------------------------------------------------------


class StdinReader:
    """Thread daemon tên "teleport-stdin": os.read(fd, 1024), tách dòng, giải mã UTF-8 errors="replace",
    đưa (time.perf_counter(), dòng) vào `lines` qua loop.call_soon_threadsafe. EOF/lỗi → (ts, None) rồi dừng.
    Hàng đợi đã có ≥ 100 mục thì bỏ dòng mới. Loop đã đóng (RuntimeError) → thread dừng.
    stdin là None hoặc không có fileno → đưa (ts, None) ngay."""

    def __init__(self, loop: asyncio.AbstractEventLoop, lines: Lines) -> None:
        self._loop = loop
        self._lines = lines

    def start(self) -> None:
        try:
            fd = sys.stdin.fileno() if sys.stdin is not None else None
        except (AttributeError, OSError, ValueError):  # pytest thay stdin bằng object không có fileno
            fd = None
        if fd is None:
            self._post(None)
            return
        threading.Thread(target=self._run, args=(fd,), name="teleport-stdin", daemon=True).start()

    def _run(self, fd: int) -> None:
        buf = bytearray()
        skipping = False  # đang bỏ phần còn lại của một dòng quá dài
        while True:
            try:
                chunk = os.read(fd, 1024)
            except OSError:
                chunk = b""
            if not chunk:
                if buf and not skipping:
                    self._post(bytes(buf))
                if _isatty(fd):
                    time.sleep(_TTY_EOF_DELAY)
                self._post(None)
                return
            buf += chunk
            while (end := buf.find(b"\n")) >= 0:
                line = bytes(buf[:end])
                del buf[: end + 1]
                if skipping:
                    skipping = False
                elif not self._post(line):
                    return
            if len(buf) > _MAX_LINE_BYTES:
                buf.clear()
                skipping = True

    def _post(self, line: bytes | None) -> bool:
        """Đưa một dòng sang loop; False khi loop đã đóng (thread nên dừng)."""
        read_at = time.perf_counter()
        text = None if line is None else line.decode("utf-8", errors="replace").rstrip("\r")
        try:
            self._loop.call_soon_threadsafe(self._put, read_at, text)
        except RuntimeError:
            return False
        return True

    def _put(self, read_at: float, text: str | None) -> None:
        if text is not None and self._lines.qsize() >= _MAX_QUEUED_LINES:
            return  # EOF luôn được đưa vào, để lời hỏi không treo
        self._lines.put_nowait((read_at, text))


def _isatty(fd: int) -> bool:
    try:
        return os.isatty(fd)
    except OSError:
        return False


RunFn = Callable[[argparse.Namespace, Lines, TextIO, TextIO], Awaitable[int]]


async def _main(args: argparse.Namespace, run: RunFn) -> int:
    loop = asyncio.get_running_loop()
    lines: Lines = asyncio.Queue()
    StdinReader(loop, lines).start()
    restore = _handle_ctrl_break(loop, asyncio.current_task())
    try:
        return await run(args, lines, sys.stdout, sys.stderr)
    finally:
        restore()


def _handle_ctrl_break(loop: asyncio.AbstractEventLoop, task: asyncio.Task | None) -> Callable[[], None]:
    """Windows: Ctrl+Break (SIGBREAK) hủy lệnh như Ctrl+C. Trả hàm khôi phục handler cũ."""
    sig = getattr(signal, "SIGBREAK", None)
    if sig is None or task is None:
        return lambda: None

    def handler(signum: int, frame: object) -> None:
        loop.call_soon_threadsafe(task.cancel)

    try:
        previous = signal.signal(sig, handler)
    except (ValueError, OSError):  # không ở thread chính
        return lambda: None

    def restore() -> None:
        signal.signal(sig, previous)

    return restore


def _run_async(args: argparse.Namespace, run: RunFn) -> int | None:
    """Chạy lệnh trong event loop riêng; bị hủy (Ctrl+C, Ctrl+Break) → None."""
    with asyncio.Runner() as runner:
        try:
            return runner.run(_main(args, run))
        except (KeyboardInterrupt, asyncio.CancelledError):
            return None


def cmd_listen(args: argparse.Namespace) -> int:
    code = _run_async(args, run_listen)
    if code is not None:
        return code
    output = _Output(sys.stdout, sys.stderr, args.json)
    output.text("Đã dừng.")
    output.event("stopped")
    return 0


async def _list_main(args: argparse.Namespace) -> int:
    restore = _handle_ctrl_break(asyncio.get_running_loop(), asyncio.current_task())
    try:
        return await run_list(args, sys.stdout, sys.stderr)
    finally:
        restore()


def cmd_list(args: argparse.Namespace) -> int:
    with asyncio.Runner() as runner:
        try:
            return runner.run(_list_main(args))
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
    output = _Output(sys.stdout, sys.stderr, args.json)
    output.text("Đã hủy.")
    output.event("error", error="cancelled", message="Đã hủy.")
    return 1


def cmd_pair(args: argparse.Namespace) -> int:
    state = _PairState()
    code = _run_async(args, functools.partial(run_pair, state=state))
    if code is not None:
        return code
    # Bị hủy (Ctrl+C, Ctrl+Break). Kết quả đã có thì nó mới là sự thật, kể cả khi lệnh hủy
    # tới lúc đang đóng kết nối hay đóng node: đã in thì thôi, chưa in thì in bây giờ.
    result = state.result
    if result is not None and (state.emitted or result.outcome is not PairingOutcome.CANCELLED):
        if not state.emitted:
            _emit_result(_Output(sys.stdout, sys.stderr, args.json), result, seen_name=state.seen_name)
        return 0 if result.outcome is _PAIRED else 1
    output = _Output(sys.stdout, sys.stderr, args.json)
    message = "Đã hủy ghép đôi."
    output.text(message)
    try:
        target, endpoint = _pair_target(args.address)
        address = target if endpoint is None else endpoint[0]  # như PairingFinished.address: chỉ IPv4
    except ValueError:
        address = args.address.strip()
    output.event(
        "pair_result",
        session_id=None,
        role="initiator",
        outcome=PairingOutcome.CANCELLED.value,
        peer_name=None,
        peer_device_id=None,
        address=address,
        message=message,
    )
    return 1


# ---- Truyền file: câu chữ --------------------------------------------------------------------

# Seam cấp module, đọc lúc dùng (test vá bằng monkeypatch).
_SEND_CONNECT_TIMEOUT = 20.0  # send qua mDNS: chờ kết nối tới máy nhận tối đa (giây)
_PLAIN_PROGRESS_INTERVAL = 10.0  # không TTY: in dòng tiến độ tối đa một lần mỗi 10 s mỗi lượt
_OFFER_LIST_MAX = 10  # lời hỏi nhận file: số file liệt kê tối đa, còn lại gộp một dòng

_MAX_RATE = 1 << 40  # --limit-rate tối đa (byte/giây)
_MAX_RATE_TEXT = 64  # chuỗi --limit-rate dài hơn thì sai luôn (không đổi số khổng lồ)
_RATE_RE = re.compile(r"\s*(\d+(?:[.,]\d+)?)\s*([kKmMgG])?[bB]?(?:/s)?\s*", re.ASCII)
_RATE_UNITS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
_GLOB_CHARS = frozenset("*?[")
_REPLACEMENT = "�"  # U+FFFD: ký tự điều khiển trong tên file cục bộ (mvp mục 8)

_STOPPING = "Đang dừng… (nhấn Ctrl+C lần nữa để thoát ngay)"
_CANCELLED = "Đã hủy."
_RECONNECTING = "Đang nối lại…"
_NODE_LOCKED_HINT = (
    "Hãy dừng `teleport receive` hoặc `teleport listen` đang chạy, "
    "hoặc chọn Thoát trong menu khay của Teleport, rồi thử lại."
)
_ASK_RECEIVE = "Nhận? [c/k]: "
_STDIN_CLOSED = "Không đọc được câu trả lời (đầu vào đã đóng) nên đã từ chối. Hãy dùng `--yes` để tự nhận."
_RECEIVE_REJECTED = "Đã từ chối."
_PAIR_STDIN_CLOSED = "Không đọc được câu trả lời (đầu vào đã đóng) nên đã từ chối ghép đôi."


def _terminal_width() -> int:
    """Số cột của terminal (seam cho test)."""
    return shutil.get_terminal_size().columns


def _printable(text: str) -> str:
    """Ký tự điều khiển (Cc), surrogate lẻ (Cs) và ký tự vô hình / điều khiển hướng chữ
    (`core.filenames.INVISIBLE_CHARS`) → U+FFFD, trước khi in tên hay đường dẫn.

    Tên file nhận đã được làm sạch ở `core.filenames`, tên file và đường dẫn trên máy này thì
    chưa (mvp mục 8: ký tự điều khiển không in thẳng ra màn hình); thay cả ở đây để không phụ
    thuộc một tầng làm sạch duy nhất.
    """
    return "".join(
        _REPLACEMENT if ch in INVISIBLE_CHARS or unicodedata.category(ch) in ("Cc", "Cs") else ch
        for ch in text
    )


def _file_label(name: str) -> str:
    return display_filename(_printable(name))


def _name_label(name: str) -> str:
    """Tên máy để in (không ngoặc): `_printable` rồi `display_name`.

    Tên máy đã qua `validate_device_name` (ở `trusted.json`, mDNS hay ghép đôi); vẫn qua `_printable`
    (phòng thủ chiều sâu, không đổi tên hợp lệ), nên mọi chỗ in cùng một tên ra cùng một chuỗi.
    """
    return display_name(_printable(name))


def _peer_label(name: str | None, device_id: str) -> str:
    """Tên máy kia trong câu (không ngoặc): `_name_label`, không có tên thì 8 ký tự đầu của mã."""
    return _name_label(name) if name else _printable(device_id[:8])


def _file_at(info: TransferInfo, index: int | None) -> str:
    """Tên file thứ `index` (None: `info.file_index`) của lượt, kẹp trong khoảng hợp lệ."""
    if not info.names:
        return "?"
    i = info.file_index if index is None else index
    return _file_label(info.names[min(max(i, 0), len(info.names) - 1)])


def _drive_label(receive_dir: Path | None) -> str:
    """Cách gọi ổ chứa thư mục nhận (mvp mục 8): “ổ D:”, “ổ mạng \\\\máy\\chia-sẻ”, “ổ chứa /home/…”."""
    if receive_dir is None:
        return "ổ lưu file"
    text = str(receive_dir)
    if sys.platform == "win32":
        if text.startswith("\\\\?\\UNC\\"):
            text = "\\\\" + text[len("\\\\?\\UNC\\") :]
        elif text.startswith("\\\\?\\"):
            text = text[len("\\\\?\\") :]
        drive = ntpath.splitdrive(text)[0]
        if drive.startswith(("\\\\", "//")):
            return f"ổ mạng {_printable(drive)}"
        if drive:
            return f"ổ {_printable(drive.upper())}"
    return f"ổ chứa {_printable(text)}"


def _dir_label(receive_dir: Path | None) -> str:
    return "thư mục nhận" if receive_dir is None else _printable(str(receive_dir))


def transfer_result_message(
    finished: TransferFinished, *, peer_name: str | None, receive_dir: Path | None
) -> list[str]:
    """Câu báo kết quả một lượt truyền (docs/mvp.md mục 8); `[]` khi chỉ báo qua JSON.

    `peer_name`: tên máy kia (chưa qua `display_name`; None → 8 ký tự đầu của mã). `receive_dir`:
    thư mục nhận (bên nhận: câu lỗi ghi đĩa, câu từ chối vì ổ). Tên file theo
    `finished.file_index` (không có thì `info.file_index`), kẹp trong khoảng hợp lệ.
    """
    info = finished.info
    p = _peer_label(peer_name, info.key.device_id)
    if info.key.direction is Direction.SEND:
        return [_send_result(finished, p)]
    return _receive_result(finished, p, receive_dir)


def _send_result(finished: TransferFinished, p: str) -> str:
    info, result, reject = finished.info, finished.result, finished.reject
    file = _file_at(info, finished.file_index)
    if result is TransferResult.DONE:
        return f"Đã gửi xong {len(info.files)} file ({format_size(info.total_bytes)}) tới {p}."
    if (
        result is TransferResult.REJECTED_NO_SPACE
        and reject is not None
        and reject.needed is not None
        and reject.available is not None
    ):
        return (
            f"{p} không đủ chỗ trống để nhận: cần {format_size(reject.needed)}, "
            f"ổ lưu file trên máy đó còn {format_size(reject.available)}."
        )
    if result is TransferResult.REJECTED_FILE_TOO_LARGE and reject is not None:
        index, max_size = reject.file_index, reject.max_size
        if index is not None and max_size is not None and 0 <= index < len(info.files):
            return (
                f"{p} không nhận được {_file_at(info, index)} ({format_size(info.files[index].size)}): "
                f"ổ lưu file trên máy đó chỉ chứa được file nhỏ hơn {format_size(max_size + 1, trim=True)}."
            )
    if result is TransferResult.REJECTED_NOT_RECEIVING:
        return f"{p} chưa bật nhận file. Trên máy đó hãy chạy `teleport receive` rồi gửi lại."
    if result in _REJECTED:
        return f"{p} đã từ chối nhận file."
    if result is TransferResult.CANCELLED_USER:
        if finished.by_peer:
            return f"{p} đã dừng nhận giữa chừng. Các file đã gửi xong vẫn nằm trên máy đó."
        return f"Đã hủy lượt gửi tới {p}. Các file đã gửi xong vẫn nằm trên máy đó."
    if result is TransferResult.SOURCE_CHANGED:
        return f"{file} đã bị thay đổi trên máy gửi nên không thể gửi tiếp. Hãy gửi lại."
    if result is TransferResult.EXPIRED:
        return f"Mất kết nối với {p} quá lâu nên lượt gửi đã dừng. Hãy gửi lại."
    if result is TransferResult.SOURCE_READ_FAILED:
        return (
            f"Không đọc được {file} trên máy này nữa (file có thể đang bị chương trình khác khóa, "
            f"hoặc nằm trên ổ vừa bị rút ra). Đã dừng gửi tới {p}."
        )
    if result is TransferResult.PEER_ERROR:  # máy nhận gửi `cancel{error}`: lỗi đĩa, dữ liệu hỏng…
        return f"{p} gặp lỗi khi nhận nên đã dừng lượt gửi. Hãy xem thông báo trên máy đó rồi gửi lại."
    if result is TransferResult.PROTOCOL_ERROR:
        return _protocol_error(p)
    return f"{p} đã dừng lượt gửi."  # UNKNOWN_TRANSFER, CANCELLED_OTHER, UNPAIRED, CORRUPT…


_REJECTED = frozenset(
    {
        TransferResult.REJECTED_USER,
        TransferResult.REJECTED_NO_SPACE,
        TransferResult.REJECTED_FILE_TOO_LARGE,
        TransferResult.REJECTED_BUSY,
        TransferResult.REJECTED_OTHER,
    }
)
# Bên nhận: kết quả chỉ báo qua JSON (máy này tự trả lời, không phải lỗi người dùng cần biết).
# `SUSPENDED` (Ctrl+C khi đang nhận: tạm dừng, không hủy) có câu riêng, không thuộc nhóm này.
_RECEIVE_SILENT = frozenset(
    {
        TransferResult.REJECTED_BUSY,
        TransferResult.REJECTED_OTHER,
        TransferResult.REJECTED_NOT_RECEIVING,
    }
)
_KEPT = "Các file đã nhận xong vẫn giữ nguyên; hãy nhờ gửi lại."


def _rejected_no_answer(n: int, s: str) -> str:
    """Máy nhận: lượt chưa hiện lời hỏi bị từ chối vì đầu vào đã đóng (mvp mục 8)."""
    return f"Đã từ chối {n} file từ {s} vì không đọc được câu trả lời (đầu vào đã đóng)."


def _rejected_stopping(n: int, s: str) -> str:
    """Máy nhận: lượt chưa hiện lời hỏi bị từ chối vì Ctrl+C (mvp mục 8)."""
    return f"Đã từ chối {n} file từ {s} vì đang dừng nhận."


def _protocol_error(p: str) -> str:
    return (
        f"Lượt gửi với {p} đã dừng vì máy đó gửi dữ liệu không hợp lệ. "
        "Hãy cập nhật Teleport trên cả hai máy rồi thử lại."
    )


def _receive_result(finished: TransferFinished, s: str, receive_dir: Path | None) -> list[str]:
    info, result, reject = finished.info, finished.result, finished.reject
    file = _file_at(info, finished.file_index)
    n = len(info.files)
    if result is TransferResult.DONE:
        return [f"Đã nhận xong {n} file ({format_size(info.total_bytes)}) từ {s}."]
    if result is TransferResult.REJECTED_USER and not finished.by_peer:
        return [_RECEIVE_REJECTED]
    if result in _RECEIVE_SILENT:
        return []
    if result is TransferResult.SUSPENDED:
        # “24 giờ” là `RECONNECT_GRACE`, viết thẳng trong câu. Không in `--dir` thật.
        what = f"{n} file" if n > 1 else file
        return [
            f"Đã tạm dừng nhận {what} từ {s}. Chạy lại `teleport receive` (cùng thư mục nhận) để nhận "
            "tiếp phần còn thiếu, miễn là máy gửi vẫn đang chờ; quá 24 giờ kể từ lúc mất kết nối thì "
            "lần chạy sau sẽ xóa phần nhận dở."
        ]
    if (
        result is TransferResult.REJECTED_NO_SPACE
        and reject is not None
        and reject.needed is not None
        and reject.available is not None
    ):
        return [
            f"Đã từ chối {n} file từ {s}: không đủ chỗ trống, cần {format_size(reject.needed)}, "
            f"{_drive_label(receive_dir)} còn {format_size(reject.available)}."
        ]
    if result is TransferResult.REJECTED_FILE_TOO_LARGE and reject is not None:
        index, max_size = reject.file_index, reject.max_size
        if index is not None and max_size is not None and 0 <= index < n:
            return [
                f"Đã từ chối {n} file từ {s}: {_drive_label(receive_dir)} chỉ chứa được file nhỏ hơn "
                f"{format_size(max_size + 1, trim=True)}, mà {_file_at(info, index)} nặng "
                f"{format_size(info.files[index].size)}."
            ]
    if result is TransferResult.CANCELLED_USER:
        if not finished.by_peer:
            return [f"Đã hủy nhận từ {s}. File đã nhận xong vẫn giữ nguyên."]
        if info.status in (TransferStatus.WAITING, TransferStatus.QUEUED):
            return [f"{s} đã hủy lượt gửi."]  # hủy khi máy này còn đang hỏi / xếp hàng
        return [
            f"{s} đã hủy lượt gửi. Các file chưa nhận xong đã được xóa; file đã nhận xong vẫn giữ nguyên."
        ]
    if result is TransferResult.SOURCE_CHANGED:
        return [f"{file} đã bị thay đổi trên {s} nên không nhận tiếp được. {_KEPT}"]
    if result is TransferResult.EXPIRED:
        return [
            f"Mất kết nối với {s} quá lâu nên đã dừng nhận. "
            "Các file chưa nhận xong đã được xóa; file đã nhận xong vẫn giữ nguyên."
        ]
    if result is TransferResult.DISK_FAILED:
        return [
            f"Không lưu được {file} vào {_dir_label(receive_dir)} vì ổ đĩa báo lỗi khi ghi "
            f"(ổ có thể đã đầy, bị rút ra hoặc bị hỏng). Đã dừng nhận từ {s}; "
            "các file đã nhận xong vẫn giữ nguyên."
        ]
    if result is TransferResult.RECEIVE_DIR_MISSING:
        return [
            f"Không nhận được lượt gửi từ {s} vì thư mục nhận {_dir_label(receive_dir)} không còn "
            "hoặc không dùng được, và Teleport không tạo lại được (có thể thư mục chứa nó đã bị xóa, "
            "hoặc ổ đã bị rút ra). "
            "Hãy kiểm tra lại rồi nhờ gửi lại."
        ]
    if result is TransferResult.TEMP_EXISTS:
        return [
            f"Không nhận được lượt gửi từ {s} vì thư mục tạm của lượt này đã có sẵn mà Teleport "
            "không dùng tiếp được. Hãy nhờ gửi lại."
        ]
    if result is TransferResult.CORRUPT:
        return [f"Dữ liệu nhận từ {s} bị hỏng nhiều lần liên tiếp nên đã dừng nhận {file}. {_KEPT}"]
    if result is TransferResult.PEER_ERROR:
        return [f"{s} đã dừng gửi {file} vì gặp lỗi trên máy đó. {_KEPT}"]
    if result is TransferResult.UNKNOWN_TRANSFER:
        return [f"{s} đã hủy lượt gửi {file}. Hãy nhờ gửi lại."]
    if result is TransferResult.PROTOCOL_ERROR:
        return [_protocol_error(s)]
    return [f"{s} đã dừng lượt gửi."]  # CANCELLED_OTHER, UNPAIRED…


def transfer_resumed_message(info: TransferInfo, *, peer_name: str | None) -> str:
    """Câu báo lượt nhận dở được khôi phục khi khởi động (`TransferResumed`, docs/mvp.md mục 8).

    `peer_name`: tên máy gửi (chưa qua `display_name`; None → 8 ký tự đầu của mã). Số file là
    `len(info.files)`; dung lượng đã nhận / tổng qua `format_size`.
    """
    p = _peer_label(peer_name, info.key.device_id)
    done = format_size(max(0, info.done_bytes))
    total = format_size(max(0, info.total_bytes))
    return (
        f"Tiếp tục nhận {len(info.files)} file từ {p} (đã nhận {done} / {total}). "
        "Đang chờ máy đó kết nối lại…"
    )


def offer_prompt_lines(offer: OfferReceived, *, peer_name: str | None, receive_dir: Path | None) -> list[str]:
    """Các dòng của lời hỏi nhận file trước câu “Nhận? [c/k]: ” (docs/mvp.md mục 7.3, bản CLI).

    Tiêu đề có tên máy gửi trong “…” (`display_name`), rồi tối đa `_OFFER_LIST_MAX` dòng
    “tên file  dung lượng” (tên qua `display_filename`, cột dung lượng thẳng hàng), dòng
    “… và N file khác” nếu còn, rồi “Lưu vào: …”.
    """
    p = _peer_label(peer_name, offer.key.device_id)
    n = len(offer.files)
    lines = [f"“{p}” muốn gửi {n} file ({format_size(offer.total_bytes)}):"]
    limit = _OFFER_LIST_MAX
    shown = [
        (_file_label(name), format_size(entry.size))
        for name, entry in zip(offer.names[:limit], offer.files[:limit], strict=False)
    ]
    column = max((text_width(name) for name, _ in shown), default=0) + 4
    for name, size in shown:
        lines.append(f"  {name}{' ' * (column - text_width(name))}{size}")
    if n > len(shown):
        lines.append(f"  … và {n - len(shown)} file khác")
    lines.append(f"Lưu vào: {_dir_label(receive_dir)}")
    return lines


def _percent_tenths(done: int, total: int) -> int:
    """Phần nghìn đã xong, làm tròn xuống (không hiện 100,0% trước khi xong); total 0 → 1000."""
    if total <= 0:
        return 1000
    return min(1000, max(0, done) * 1000 // total)


def _cut(text: str, limit: int) -> str:
    """Cắt `text` ở cuối cho vừa `limit` cột (kèm `…`)."""
    if text_width(text) <= limit:
        return text
    if limit <= 0:
        return ""
    used = 0
    end = 0
    for ch in text:
        width = text_width(ch)
        if used + width > limit - 1:
            break
        used += width
        end += 1
    return text[:end] + "…"


def progress_line(update: TransferProgress, *, peer_name: str | None, width: int | None) -> str:
    """Dòng tiến độ: `  42,0% · 3,4 GB / 8,4 GB · 85,2 MB/s · còn 1 phút 2 giây · video.mp4 (1/3)`.

    `peer_name` khác None (lệnh `receive`): thêm tiền tố tên máy gửi. Chưa đo được tốc độ (`eta`
    None): “đang tính thời gian còn lại”. `width`: số cột của terminal; dòng trả về ≤ `width` − 1
    cột (cột cuối để trống, terminal không tự xuống dòng), cắt ở cuối kèm `…`; None: không cắt.
    """
    info = update.info
    tenths = _percent_tenths(info.done_bytes, info.total_bytes)
    speed = update.bytes_per_second
    speed_bytes = int(speed) if math.isfinite(speed) and speed > 0 else 0
    eta = update.eta
    remaining = (
        "đang tính thời gian còn lại"
        if eta is None or not math.isfinite(eta)
        else f"còn {format_duration(eta)}"
    )
    parts = [
        f"{tenths // 10},{tenths % 10}%",
        f"{format_size(max(0, info.done_bytes))} / {format_size(max(0, info.total_bytes))}",
        f"{format_size(speed_bytes)}/s",
        remaining,
    ]
    n = len(info.names)
    if n:
        i = min(max(info.file_index, 0), n - 1)
        parts.append(f"{_file_label(info.names[i])} ({i + 1}/{n})")
    prefix = "" if peer_name is None else f"{_peer_label(peer_name, info.key.device_id)}: "
    line = "  " + prefix + " · ".join(parts)
    return line if width is None else _cut(line, width - 1)


def parse_rate(text: str) -> int:
    """`--limit-rate` → byte/giây: “20M”, “512K”, “1,5M”, “64KB/s”, “65536” (hệ nhị phân, làm tròn xuống).

    Chỉ chữ số ASCII; hậu tố K/M/G không phân biệt hoa thường, sau đó tùy chọn “B” và “/s”;
    không hậu tố là byte/giây. Sai dạng, hoặc ngoài `transfers.MIN_RATE_LIMIT` … 2⁴⁰ → ValueError.
    """
    if not isinstance(text, str) or len(text) > _MAX_RATE_TEXT:
        raise ValueError("tốc độ không hợp lệ")
    match = _RATE_RE.fullmatch(text)
    if match is None:
        raise ValueError("tốc độ không hợp lệ")
    number = Decimal(match.group(1).replace(",", "."))
    unit = _RATE_UNITS[(match.group(2) or "").lower()]
    value = int((number * unit).to_integral_value(rounding=ROUND_FLOOR))
    if not app_transfers.MIN_RATE_LIMIT <= value <= _MAX_RATE:
        raise ValueError("tốc độ ngoài khoảng cho phép")
    return value


def source_error_message(error: SourceError) -> tuple[int, str, list[str]]:
    """File không gửi được → `(mã thoát, mã lỗi JSON, các dòng)`; thư mục là lỗi cách dùng (mã 2)."""
    path = error.path
    name = _file_label(path.name or str(path))
    kind = error.kind
    if kind is SourceErrorKind.NOT_A_FILE:
        return (
            2,
            "not_a_file",
            [f"{name} không phải là file. Teleport chưa gửi được cả thư mục; hãy chọn từng file."],
        )
    if kind is SourceErrorKind.NOT_FOUND:
        return 1, "source_not_found", [f"Không tìm thấy file {_printable(str(path))}."]
    if kind is SourceErrorKind.PERMISSION:
        return 1, "source_permission", [f"Không mở được {name}: máy này không có quyền đọc file đó."]
    if kind is SourceErrorKind.TOO_LARGE:
        size = "?" if error.size is None else format_size(error.size)
        limit = format_size(app_sources.MAX_FILE_SIZE, trim=True)
        return (
            1,
            "source_too_large",
            [
                f"Không gửi được {name} ({size}): Teleport chỉ gửi được file tối đa {limit}. "
                "Hãy chia file thành nhiều phần nhỏ hơn rồi gửi."
            ],
        )
    if kind is SourceErrorKind.BAD_NAME:
        return (
            1,
            "source_bad_name",
            [f"Không gửi được {name}: tên file có ký tự không hiển thị được. Hãy đổi tên file rồi gửi lại."],
        )
    return 1, "source_os_error", [f"Không đọc được {name}: ổ đĩa báo lỗi."]


def receive_dir_error_message(error: ReceiveDirUnavailable) -> list[str]:
    """Câu báo không dùng được thư mục nhận, theo lỗi gốc (`__cause__`).

    `NotADirectoryError` / `FileExistsError`: đường dẫn là file (POSIX: cả khi một thư mục
    cha là file; Windows báo ca đó bằng `FileNotFoundError` nên ra câu ổ đĩa).
    """
    head = f"Không dùng được thư mục nhận {_printable(str(error.path))}:"
    cause = error.__cause__
    if isinstance(cause, UnsafeReceiveDirError):
        tail = (
            "thư mục ẩn `.teleport` bên trong là liên kết hoặc thuộc người dùng khác. "
            "Hãy xóa nó hoặc chọn thư mục khác bằng `--dir`."
        )
    elif isinstance(cause, PathTooLongError):
        tail = "đường dẫn quá dài. Hãy chọn thư mục có đường dẫn ngắn hơn bằng `--dir`."
    elif isinstance(cause, NotADirectoryError | FileExistsError):
        tail = "đó không phải là thư mục (có thể là một file trùng tên). Hãy chọn thư mục khác bằng `--dir`."
    elif isinstance(cause, PermissionError):
        tail = "máy này không có quyền ghi vào đó. Hãy chọn thư mục khác bằng `--dir`."
    else:
        tail = "ổ đĩa báo lỗi hoặc không phản hồi. Hãy chọn thư mục khác bằng `--dir`."
    return [f"{head} {tail}"]


def _reconnect_unreachable_message(p: str) -> str:
    """`send` đang chờ nối lại mà `core.links` báo không tới được máy nhận (mvp mục 8).

    “24 giờ” là `RECONNECT_GRACE`, viết thẳng trong câu.
    """
    return (
        f"Chưa nối lại được với {p}. Teleport vẫn đang thử lại (tối đa 24 giờ). "
        "Hãy kiểm tra máy đó vẫn đang chạy `teleport receive` và hai máy còn chung một mạng."
    )


def _unreachable_data_message(p: str) -> str:
    return (
        f"Không mở được kết nối truyền dữ liệu tới {p}; tường lửa trên máy đó có thể đang chặn Teleport. "
        "Teleport vẫn đang thử lại."
    )


# ---- Truyền file: Ctrl+C và đóng node --------------------------------------------------------


class Interrupts:
    """Ctrl+C của `send` / `receive`: lần đầu đặt `stop` (dừng có trật tự), lần hai đặt `hard`.

    Handler tín hiệu chỉ gọi `press()` trên event loop (bẫy tín hiệu ở docstring module); test
    gọi `press()` trực tiếp.
    """

    def __init__(self) -> None:
        self.stop = asyncio.Event()
        self.hard = asyncio.Event()

    def press(self) -> None:
        if self.stop.is_set():
            self.hard.set()
        else:
            self.stop.set()


class _Session:
    """Trạng thái chung của một lần chạy `send` / `receive`: node (task làm việc không sở hữu nó)."""

    def __init__(self) -> None:
        self.node: Node | None = None
        self.stopping = False  # đã có Ctrl+C lần đầu: không mở lời hỏi mới

    def on_stop(self) -> None:
        """Ctrl+C lần đầu (trước khi in “Đang dừng…”)."""
        self.stopping = True

    def after_stopping(self) -> None:
        """Đã in “Đang dừng…”, trước khi hủy task làm việc và đóng node."""


async def _close_node(node: Node, interrupts: Interrupts) -> None:
    """`node.close()` có trật tự trong task riêng (không bị hủy), tối đa `close_time_limit()` giây.

    Ctrl+C lần hai hay hết hạn → hủy `close()`: nó tự hủy cứng mọi thứ còn lại rồi nhả khóa.
    """
    closing = asyncio.create_task(node.close(), name="teleport.cli.close")
    hard = asyncio.create_task(interrupts.hard.wait(), name="teleport.cli.hard")
    try:
        await asyncio.wait(
            {closing, hard}, timeout=app_node.close_time_limit(), return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        hard.cancel()
        if not closing.done():
            closing.cancel()
        await asyncio.wait({closing, hard})
    if not closing.cancelled() and (error := closing.exception()) is not None:
        log.error("đóng node lỗi: %s", type(error).__name__)


async def _supervise(
    work: Coroutine[Any, Any, int], session: _Session, output: _Output, interrupts: Interrupts
) -> int | None:
    """Chạy `work` tới khi xong hoặc tới lần Ctrl+C đầu (in “Đang dừng…”, hủy `work`), rồi đóng node.

    Trả mã thoát của `work`; None nếu bị dừng trước khi `work` xong. Lệnh bị hủy từ ngoài
    (test) vẫn đóng node trước khi CancelledError bay ra.
    """
    task = asyncio.create_task(work, name="teleport.cli.work")
    stop = asyncio.create_task(interrupts.stop.wait(), name="teleport.cli.stop")
    try:
        await asyncio.wait({task, stop}, return_when=asyncio.FIRST_COMPLETED)
        if not task.done():
            session.on_stop()
            output.text(_STOPPING)
            session.after_stopping()
            task.cancel()
            await asyncio.wait({task})
    finally:
        stop.cancel()
        if not task.done():
            task.cancel()
            await asyncio.wait({task})
        await asyncio.wait({stop})
        if session.node is not None:
            await _close_node(session.node, interrupts)
    if task.cancelled():
        return None
    return task.result()


def _check_node_args(args: argparse.Namespace, output: _Output) -> bool:
    """`--host`, `--name` của `send` / `receive`; sai → in lỗi, False (mã thoát 2)."""
    host = getattr(args, "host", _ANY_HOST)
    if not _valid_host(host):
        output.error("invalid_address", f"Địa chỉ lắng nghe không hợp lệ: {host!r}")
        return False
    name = getattr(args, "name", None)
    if name is not None:
        try:
            validate_device_name(name)
        except MessageError as e:
            output.error("invalid_name", f"Tên thiết bị không hợp lệ: {e}")
            return False
    return True


async def _start_transfer_node(node: Node, output: _Output) -> int | None:
    """`node.start()` của `send` / `receive`; lỗi → in lỗi, trả mã thoát. Thành công → None."""
    try:
        await node.start()
    except NodeLockedError:
        output.error("node_locked", "Teleport đang chạy với thư mục cấu hình này.", extra=[_NODE_LOCKED_HINT])
        return 1
    except IdentityError as e:
        output.error("identity_error", str(e))
        return 1
    except TrustStoreError as e:
        output.error("trust_store_error", str(e))
        return 1
    except ConfigDirError as e:
        _config_dir_error(output, e.path, e.error)
        return 1
    except ReceiveDirUnavailable as e:
        lines = receive_dir_error_message(e)
        output.error("receive_dir_error", lines[0], extra=lines[1:], path=str(e.path))
        return 1
    except OSError as e:  # Node.start: OSError còn lại chỉ đến từ cổng lắng nghe
        output.error("port_unavailable", f"Không mở được cổng để lắng nghe: {e}")
        return 1
    return None


# ---- Truyền file: sự kiện --------------------------------------------------------------------


def _key_of(update: TransferUpdate) -> TransferKey | None:
    if isinstance(update, OfferReceived | FileDone):
        return update.key
    if isinstance(update, TransferStatusChanged | TransferProgress | TransferFinished | TransferResumed):
        return update.info.key
    return None  # DataUnreachable: chỉ có device_id


def _transfer_fields(key: TransferKey) -> dict[str, Any]:
    return {"transfer_id": key.transfer_id, "direction": key.direction.value, "device_id": key.device_id}


class _TransferPrinter:
    """In sự kiện của lượt truyền (trạng thái, tiến độ, file xong, kết quả) ở chế độ text và JSON.

    `name_of(device_id)`: tên máy kia (chưa qua `display_name`); `receive_dir()`: thư mục nhận.
    `prefix`: dòng tiến độ có tiền tố tên máy kia (`receive`, nhiều lượt cùng lúc).
    """

    def __init__(
        self,
        output: _Output,
        *,
        name_of: Callable[[str], str | None],
        receive_dir: Callable[[], Path | None],
        prefix: bool,
    ) -> None:
        self._output = output
        self._name_of = name_of
        self._receive_dir = receive_dir
        self._prefix = prefix
        self._file_counts: dict[TransferKey, int] = {}
        self._plain_at: dict[TransferKey, float] = {}  # không TTY: lúc in dòng tiến độ gần nhất
        # `done_bytes` của lần in tiến độ gần nhất: app vẫn phát `TransferProgress` khi lượt đứng
        # yên, CLI chỉ in (text và JSON) khi `done_bytes` đổi.
        self._printed_done: dict[TransferKey, int] = {}

    def _peer(self, device_id: str) -> str:
        return _peer_label(self._name_of(device_id), device_id)

    def note_files(self, key: TransferKey, count: int) -> None:
        self._file_counts[key] = count

    def handle(self, update: TransferUpdate) -> None:
        if isinstance(update, TransferStatusChanged):
            self.status(update.info)
        elif isinstance(update, TransferResumed):
            self._resumed(update.info)
        elif isinstance(update, TransferProgress):
            self._progress(update)
        elif isinstance(update, FileDone):
            self._file_done(update)
        elif isinstance(update, TransferFinished):
            self.finished(update)
        elif isinstance(update, DataUnreachable):
            self._unreachable(update.device_id)

    def status(self, info: TransferInfo, *, quiet_reconnecting: bool = False) -> None:
        """Trạng thái mới của lượt. `quiet_reconnecting`: không in dòng “Đang nối lại…” (JSON vẫn có)."""
        key = info.key
        self.note_files(key, len(info.files))
        out = self._output
        out.event("status", **_transfer_fields(key), status=info.status.value)
        sending = key.direction is Direction.SEND
        status = info.status
        if status is TransferStatus.QUEUED and sending:
            out.text(f"Đang chờ {self._peer(key.device_id)} nhận xong lượt trước…")
        elif status is TransferStatus.WAITING and sending:
            out.text(f"Đang chờ {self._peer(key.device_id)} trả lời…")
        elif status is TransferStatus.RECONNECTING:
            if not quiet_reconnecting:
                out.text(_RECONNECTING)
        elif status is TransferStatus.VERIFYING:
            out.text(f"Đang kiểm tra {_file_at(info, None)}…")

    def _resumed(self, info: TransferInfo) -> None:
        """Lượt nhận dở được khôi phục khi khởi động: câu (mvp mục 8) và sự kiện JSON `restored`."""
        key = info.key
        self.note_files(key, len(info.files))
        name = self._name_of(key.device_id)
        receive_dir = self._receive_dir()
        out = self._output
        out.text(transfer_resumed_message(info, peer_name=name))
        out.event(
            "restored",
            **_transfer_fields(key),
            device_name=name,
            files=[{"name": n, "size": e.size} for n, e in zip(info.names, info.files, strict=False)],
            total_bytes=info.total_bytes,
            done_bytes=info.done_bytes,
            file_index=info.file_index,
            file_count=len(info.files),
            receive_dir=None if receive_dir is None else str(receive_dir),
        )

    def _progress(self, update: TransferProgress) -> None:
        info = update.info
        key = info.key
        self.note_files(key, len(info.files))
        if self._printed_done.get(key) == info.done_bytes:
            return
        self._printed_done[key] = info.done_bytes
        out = self._output
        speed = update.bytes_per_second
        eta = update.eta
        out.event(
            "progress",
            **_transfer_fields(key),
            done_bytes=info.done_bytes,
            total_bytes=info.total_bytes,
            percent=_percent_tenths(info.done_bytes, info.total_bytes) / 10,
            bytes_per_second=int(speed) if math.isfinite(speed) and speed > 0 else 0,
            eta_seconds=eta if eta is not None and math.isfinite(eta) else None,
            file_index=info.file_index,
            file_count=len(info.files),
        )
        if out.json:
            return
        peer = (self._name_of(key.device_id) or key.device_id[:8]) if self._prefix else None
        if out.tty:
            out.progress(progress_line(update, peer_name=peer, width=_terminal_width()))
            return
        now = time.monotonic()
        last = self._plain_at.get(key)
        if last is None or now - last >= _PLAIN_PROGRESS_INTERVAL:
            self._plain_at[key] = now
            out.text(progress_line(update, peer_name=peer, width=None))

    def _file_done(self, update: FileDone) -> None:
        key = update.key
        out = self._output
        path = None if update.path is None else str(update.path)
        out.event(
            "file_done", **_transfer_fields(key), file_index=update.file_index, name=update.name, path=path
        )
        if key.direction is Direction.SEND:
            count = self._file_counts.get(key)
            total = "?" if count is None else str(count)
            out.text(f"Đã gửi {_file_label(update.name)} ({update.file_index + 1}/{total}).")
        else:
            out.text(f"Đã lưu: {_printable(path if path is not None else update.name)}")

    def finished(self, finished: TransferFinished, *, lines: list[str] | None = None) -> None:
        """Kết quả của lượt: câu và sự kiện JSON `result`.

        `lines`: câu in thay cho câu của `transfer_result_message` (`[]`: không in); `message`
        trong JSON vẫn là câu của `transfer_result_message`.
        """
        info = finished.info
        key = info.key
        self._file_counts.pop(key, None)
        self._plain_at.pop(key, None)
        self._printed_done.pop(key, None)
        name = self._name_of(key.device_id)
        message = transfer_result_message(finished, peer_name=name, receive_dir=self._receive_dir())
        out = self._output
        out.text(*(message if lines is None else lines))
        # `payload_sent` chỉ có ở chiều gửi (bên nhận luôn 0, không in).
        sent = {"payload_sent": finished.payload_sent} if key.direction is Direction.SEND else {}
        out.event(
            "result",
            **_transfer_fields(key),
            device_name=name,
            result=finished.result.value,
            by_peer=finished.by_peer,
            reason=finished.reason,
            file_index=finished.file_index,
            files_done=info.file_index,
            file_count=len(info.files),
            done_bytes=info.done_bytes,
            total_bytes=info.total_bytes,
            **sent,
            message=" ".join(message),
        )

    def _unreachable(self, device_id: str) -> None:
        message = _unreachable_data_message(self._peer(device_id))
        self._output.text(message)
        self._output.event("data_unreachable", device_id=device_id, message=message)


# ---- send ------------------------------------------------------------------------------------


class _SendSession(_Session):
    """Trạng thái của `send`: ghi kết quả ngay trong callback, để Ctrl+C tới sau vẫn trả đúng mã."""

    def __init__(self, output: _Output) -> None:
        super().__init__()
        self.output = output
        self.device_id = ""
        self.peer_name: str | None = None  # tên trong trusted.json, chưa qua display_name
        self.connected = False  # đã có DeviceConnected của máy nhận (có thể tới trước khi chờ)
        self.failure: ConnectFailed | None = None  # ConnectFailed đầu tiên trước khi gửi
        self.sending = False  # đã gọi transfers.send: ConnectFailed sau đó chỉ in (nối lại tới 24 h)
        self.offered = False  # đã phát `offer` (JSON) cho lượt gửi
        self.result: TransferFinished | None = None
        self.wake = asyncio.Event()  # có sự kiện kết nối mới
        self.done = asyncio.Event()  # có `result`
        self.printer = _TransferPrinter(
            output, name_of=lambda _: self.peer_name, receive_dir=lambda: None, prefix=False
        )

    def on_event(self, event: NodeEvent) -> None:
        view = event.device
        if view.device_id != self.device_id:
            return
        if isinstance(event, DeviceConnected):
            self.connected = True
            self.wake.set()
        elif isinstance(event, ConnectFailed):
            if self.sending and event.result is ConnectResult.UNREACHABLE:
                # Đang chờ nối lại: không phải câu “mạng chặn” (mvp mục 8, “Mất mạng”). Mỗi đợt mất
                # kết nối `core.links` chỉ báo một lần.
                self.output.text(_reconnect_unreachable_message(_peer_label(self.peer_name, self.device_id)))
            elif self.sending:
                self.output.text(*connect_failed_message(view, event.result))
            elif self.failure is None:
                self.failure = event
                self.wake.set()

    def on_transfer_event(self, update: TransferUpdate) -> None:
        if isinstance(update, DataUnreachable):
            if update.device_id == self.device_id:
                self.printer.handle(update)
            return
        key = _key_of(update)
        if key is None or key.direction is not Direction.SEND or key.device_id != self.device_id:
            return
        if not self.offered and isinstance(
            update, TransferStatusChanged | TransferProgress | TransferFinished
        ):
            self.offered = True
            info = update.info
            self.output.event(
                "offer",
                **_transfer_fields(key),
                device_name=self.peer_name,
                files=[{"name": n, "size": e.size} for n, e in zip(info.names, info.files, strict=False)],
                total_bytes=info.total_bytes,
            )
        self.printer.handle(update)
        if isinstance(update, TransferFinished) and self.result is None:
            self.result = update
            self.done.set()


def _expand_sources(paths: Sequence[str]) -> tuple[list[str], str | None]:
    """Windows: đường dẫn không tồn tại mà có `*?[` thì mở rộng bằng `glob` (sắp xếp), vì cmd.exe và
    PowerShell không tự mở rộng. Trả `(đường dẫn, mẫu không khớp file nào hoặc None)`."""
    if sys.platform != "win32":
        return list(paths), None
    result: list[str] = []
    for path in paths:
        if _GLOB_CHARS.isdisjoint(path) or os.path.lexists(path):
            result.append(path)
            continue
        matches = sorted(glob.glob(path))
        if not matches:
            return result, path
        result.extend(matches)
    return result, None


def _trusted_lookup_error(output: _Output, query: str, error: DeviceNotFound | AmbiguousDevice) -> None:
    """`--to` / `unpair`: không có, hoặc khớp nhiều thiết bị tin cậy."""
    if isinstance(error, AmbiguousDevice):
        output.error(
            "ambiguous",
            f"“{query}” khớp nhiều thiết bị; hãy nhập mã thiết bị dài hơn:",
            extra=[f"  {d.device_id}  {_name_label(d.name)}" for d in error.candidates],
            candidates=_candidates(error.candidates),
        )
        return
    if error.known:
        extra = [
            "Các thiết bị tin cậy:",
            *(f"  {d.device_id[:8]}  {_name_label(d.name)}" for d in error.known),
        ]
    else:
        extra = ["(chưa ghép đôi với thiết bị nào)"]
    output.error(
        "not_found",
        f"Không có thiết bị tin cậy nào khớp “{query}”.",
        extra=extra,
        candidates=_candidates(error.known),
    )


def _source_error(output: _Output, error: SourceError) -> int:
    code, kind, lines = source_error_message(error)
    output.error(kind, lines[0], extra=lines[1:])
    return code


def _duplicate_error(output: _Output) -> int:
    output.error("duplicate_file", "Có file được chọn hai lần. Hãy chọn mỗi file một lần.")
    return 2


async def run_send(
    args: argparse.Namespace, lines: Lines, out: TextIO, err: TextIO, *, interrupts: Interrupts | None = None
) -> int:
    """`teleport send <file...> --to <thiết bị>`: 0 khi gửi xong, 1 lỗi lúc chạy hay bị hủy, 2 cú pháp sai.

    `lines` không dùng (lệnh này không đọc stdin). `interrupts`: Ctrl+C (test gọi `press()`).
    Kết quả của lượt được ghi ngay trong callback, nên Ctrl+C tới sau khi xong vẫn trả 0.
    """
    interrupts = interrupts if interrupts is not None else Interrupts()
    output = _Output(out, err, bool(getattr(args, "json", False)))
    session = _SendSession(output)
    code = await _supervise(_send_main(args, output, session), session, output, interrupts)
    if session.result is not None:
        return 0 if session.result.result is TransferResult.DONE else 1
    if code is None:  # dừng trước khi có kết quả (kể cả thoát cứng trước khi kịp hủy lượt)
        output.text(_CANCELLED)
        output.event("error", error="cancelled", message=_CANCELLED)
        return 1
    return code


async def _send_main(args: argparse.Namespace, output: _Output, session: _SendSession) -> int:
    """Phần việc của `send` (task con, bị hủy khi Ctrl+C); node được `_supervise` đóng."""
    rate: int | None = None
    if args.limit_rate is not None:
        try:
            rate = parse_rate(args.limit_rate)
        except ValueError:
            output.error(
                "invalid_rate",
                f"Tốc độ không hợp lệ: “{_printable(args.limit_rate)}”. "
                "Hãy nhập ví dụ 20M (20 MB/s) hoặc 512K; tối thiểu 64K.",
            )
            return 2
    endpoint: tuple[str, int] | None = None
    if args.address is not None:
        try:
            endpoint = parse_manual_address(args.address)
        except ValueError:
            output.error(
                "invalid_address",
                f"{_printable(args.address.strip())} không phải địa chỉ IPv4 hợp lệ. "
                "Hãy nhập ví dụ 192.168.1.5 hoặc 192.168.1.5:47474.",
            )
            return 2
    if not _check_node_args(args, output):
        return 2
    paths, unmatched = _expand_sources(args.files)
    if unmatched is not None:
        output.error("source_not_found", f"Không tìm thấy file {_printable(os.path.abspath(unmatched))}.")
        return 1
    if len(paths) > MAX_OFFER_FILES:
        output.error("too_many_files", f"Mỗi lần gửi được tối đa {MAX_OFFER_FILES} file.")
        return 2
    # Kiểm thiết bị và file trước khi lấy node.lock hay đụng mạng.
    query = args.to
    try:
        device = find_trusted(_config(args), query)
    except ConfigDirError as e:
        _config_dir_error(output, e.path, e.error)
        return 1
    except TrustStoreError as e:
        output.error("trust_store_error", str(e))
        return 1
    except (DeviceNotFound, AmbiguousDevice) as e:
        _trusted_lookup_error(output, query, e)
        return 1
    try:
        files = await app_transfers.preview_sources(paths)
    except SourceError as e:
        return _source_error(output, e)
    except ValueError:
        return _duplicate_error(output)
    total = sum(f.entry.size for f in files)
    name = _name_label(device.name)
    mdns = _mdns_options(args, advertise=False)
    # Địa chỉ đã kết nối lần trước (`last_address`): node tự thử nó, kể cả khi không có mDNS.
    if mdns is None and endpoint is None and not _has_saved_address(device):
        output.error("discovery_error", _no_discovery_message(name, "đang tắt"))
        return 1
    session.device_id = device.device_id
    session.peer_name = device.name
    port = getattr(args, "port", None)
    node = Node(
        _config(args),
        name=getattr(args, "name", None),
        port=0 if port is None else port,  # cổng tạm, không lưu settings.json
        host=getattr(args, "host", _ANY_HOST),
        accept_pairing=False,
        mdns=mdns,
        auto_connect=True,
        auto_connect_to=device.device_id,
        on_event=session.on_event,
        rate_limit=rate,
        on_transfer_event=session.on_transfer_event,
    )
    session.node = node
    code = await _start_transfer_node(node, output)
    if code is not None:
        return code
    # trusted.json có thể đã đổi giữa lúc tìm và lúc lấy khóa.
    current = node.store.get(device.device_id)
    if current is None:
        _trusted_lookup_error(output, query, DeviceNotFound(query, node.store.devices()))
        return 1
    session.peer_name = current.name
    name = _name_label(current.name)
    if not node.visible:
        output.text(_HIDDEN_WARNING)
    if endpoint is not None:
        node.connect_hint(current.device_id, [endpoint[0]], endpoint[1])
        output.text(f"Đang kết nối tới “{name}” tại {endpoint[0]}:{endpoint[1]}…")
    elif not node.discovery_active and _has_saved_address(current):
        output.text(f"Đang kết nối tới “{name}” ở địa chỉ đã kết nối lần trước…")
    elif not node.discovery_active:
        reason = node.discovery_error
        output.error(
            "discovery_error", _no_discovery_message(name, "?" if reason is None else _error_text(reason))
        )
        return 1
    else:
        output.text(f"Đang tìm “{name}” trong mạng…")
    rate = node.transfers.rate_limit  # không có `--limit-rate`: giới hạn đã lưu trong cài đặt
    if rate is not None:
        output.text(f"Giới hạn tốc độ gửi: {format_size(rate, trim=True)}/s.")
    output.event(
        "connecting",
        device_id=current.device_id,
        name=current.name,
        address=None if endpoint is None else f"{endpoint[0]}:{endpoint[1]}",
        file_count=len(files),
        total_bytes=total,
        rate_limit=rate,
    )
    code = await _wait_connected(node, output, session, name, endpoint)
    if code is not None:
        return code
    output.text(f"Đã kết nối với “{name}”. Gửi {len(files)} file ({format_size(total)}).")
    session.sending = True
    try:
        await node.transfers.send(current.device_id, [f.path for f in files])
    except SourceError as e:
        return _source_error(output, e)
    except ValueError:
        return _duplicate_error(output)
    except (RuntimeError, KeyError):  # node đang đóng, hoặc máy nhận vừa thôi tin cậy
        if session.result is None:
            output.text(_CANCELLED)
            output.event("error", error="cancelled", message=_CANCELLED)
        return 1
    await session.done.wait()
    assert session.result is not None
    return 0 if session.result.result is TransferResult.DONE else 1


def _no_discovery_message(name: str, reason: str) -> str:
    return (
        f"Không tìm được {name} vì không bật được khám phá mDNS ({reason}). Hãy thêm `--address <ip[:cổng]>`."
    )


def _has_saved_address(device: TrustedDevice) -> bool:
    """Thiết bị có địa chỉ đã lưu mà node tự thử được (không phải địa chỉ Internet công khai)."""
    return device.last_address is not None and is_saveable(device.last_address[0])


async def _wait_connected(
    node: Node, output: _Output, session: _SendSession, name: str, endpoint: tuple[str, int] | None
) -> int | None:
    """Chờ kết nối điều khiển tới máy nhận. `ConnectFailed` đầu tiên → mã 1; qua mDNS: quá
    `_SEND_CONNECT_TIMEOUT` → mã 1. `--address` không có hạn: lần thử do `connect_hint` thất bại
    được `core.links` báo ngay. Kết nối được → None."""
    loop = asyncio.get_running_loop()
    deadline = None if endpoint is not None else loop.time() + _SEND_CONNECT_TIMEOUT
    device_id = session.device_id
    while True:
        if session.connected or device_id in node.connected_devices():
            return None
        failure = session.failure
        if failure is not None:
            if failure.result is ConnectResult.UNREACHABLE and endpoint is not None:
                lines = [
                    f"Không kết nối được tới {endpoint[0]}:{endpoint[1]}. Hãy kiểm tra Teleport đang chạy "
                    "trên máy đó, hai máy dùng chung một mạng, và tường lửa cho phép Teleport."
                ]
            else:
                lines = connect_failed_message(failure.device, failure.result)
            output.error(
                "connect_failed", lines[0], extra=lines[1:], result=failure.result.value, device_id=device_id
            )
            return 1
        timeout = None if deadline is None else deadline - loop.time()
        if timeout is not None and timeout <= 0:
            view = next((v for v in node.devices() if v.device_id == device_id), None)
            if view is not None and view.online:
                lines = connect_failed_message(view, ConnectResult.UNREACHABLE)
                output.error(
                    "connect_failed",
                    lines[0],
                    extra=lines[1:],
                    result=ConnectResult.UNREACHABLE.value,
                    device_id=device_id,
                )
            else:
                output.error(
                    "not_seen",
                    f"Không thấy {name} trong mạng. Hãy kiểm tra máy đó đang chạy `teleport receive` và hai "
                    "máy dùng chung một mạng; nếu mạng chặn mDNS, hãy thêm `--address <ip[:cổng]>`.",
                    device_id=device_id,
                )
            return 1
        session.wake.clear()
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(timeout):
                await session.wake.wait()


# ---- receive ---------------------------------------------------------------------------------


class _ReceiveSession(_Session):
    """Lời hỏi nhận file và in sự kiện của `receive`.

    Mỗi lần một lời hỏi; `offer` tới sau xếp hàng FIFO. Luật stdin như `_Prompter`: dòng gõ
    trước lúc hiện lời hỏi bị bỏ (`--json`: trước lúc in sự kiện `offer` của nó); EOF → từ chối
    lời hỏi đang mở và mọi lời hỏi sau. Sự kiện tới trước khi in xong phần đầu được giữ lại.

    Câu khi lượt bị từ chối không do người dùng gõ `k` (mvp mục 8; JSON `result` không đổi):
    - EOF: B13 in một lần, lúc lần đầu có lượt bị từ chối vì EOF; lượt đã hiện lời hỏi thì không
      in thêm “Đã từ chối.”; lượt chưa từng hiện (đang xếp hàng lúc EOF, hay tới sau EOF) thì in
      “Đã từ chối N file từ X vì không đọc được câu trả lời …” cho từng lượt.
    - Ctrl+C (`node.close()` từ chối mọi lượt còn chờ): lượt đang hỏi không in gì (đã có “Đang
      dừng…”); lượt chưa hiện lời hỏi (đang xếp hàng, hay chưa có `offer` vì `core` còn giữ trong
      hàng của thiết bị) in “Đã từ chối N file từ X vì đang dừng nhận.”

    Ctrl+C khi đang nhận: `node.close()` tạm dừng lượt (`TransferFinished(SUSPENDED)`), mỗi lượt
    một câu tạm dừng, sau “Đang dừng…”. Ctrl+C sau khi `Node.start` trả về mà trước khi in xong
    phần đầu thì các sự kiện đang giữ được in ngay sau “Đang dừng…” (`after_stopping`).

    Giới hạn đã biết: Ctrl+C trong lúc `Node.start` (sau bước khôi phục, lúc mở cổng hay mDNS) thì
    `node.close()` không tạm dừng lượt khôi phục, nên không có câu tạm dừng: mọi sự kiện đang giữ và
    tới sau bị bỏ (không có “Tiếp tục nhận…”, `restored` hay `result` của lượt đó). Lượt dở vẫn
    nằm trên đĩa và được khôi phục ở lần chạy sau.

    Lượt khôi phục khi khởi động (`TransferResumed`, phát trong `Node.start()`, nên in sau phần
    đầu): một câu “Tiếp tục nhận…” và sự kiện JSON `restored` thay cho `offer`, không hỏi `[c/k]`
    kể cả khi không có `--yes`. Sau đó lượt được in như lượt đã nhận, trừ dòng “Đang nối lại…”
    của trạng thái `reconnecting` ban đầu (JSON `status` vẫn có); lượt rời `reconnecting` một
    lần thì các lần mất kết nối sau in như thường. `status` chỉ được in cho lượt đã có `offer`
    hay `TransferResumed`: lượt khôi phục đã quá hạn nối lại (không có `TransferResumed`) chỉ
    có `result: expired`.

    Giới hạn: lượt bị tạm dừng trước khi thư mục tạm của nó được tạo (vài ms sau khi nhận) không
    có `transfer.json`, nên lần chạy sau không khôi phục nó mà hỏi lại `[c/k]` khi máy gửi gửi
    lại `offer`.
    """

    def __init__(self, output: _Output) -> None:
        super().__init__()
        self.output = output
        self.printer = _TransferPrinter(
            output, name_of=self._name_of, receive_dir=self._receive_dir, prefix=True
        )
        self._pending: list[Callable[[], None]] | None = []
        self._muted = False  # Ctrl+C trong lúc `Node.start`: bỏ mọi sự kiện (`after_stopping`)
        self.started = False  # `Node.start` đã trả về thành công
        self._queue: deque[tuple[OfferReceived, float]] = deque()  # (offer, lúc in sự kiện offer)
        self._current: OfferReceived | None = None
        self._shown_at = 0.0
        self._stdin_closed = False
        self._told_closed = False
        self._offered: set[TransferKey] = set()  # lượt đã phát `offer`
        self._resumed: set[TransferKey] = set()  # lượt khôi phục đã phát `restored`
        self._quiet_reconnect: set[TransferKey] = set()  # lượt khôi phục chưa rời `reconnecting` ban đầu
        self._shown: set[TransferKey] = set()  # lượt đã hiện lời hỏi (`--json`: đã tới lượt hỏi)
        self._eof_rejected: set[TransferKey] = set()  # đã từ chối vì đầu vào đóng (B13 / M14 thay C6)

    def _name_of(self, device_id: str) -> str | None:
        if self.node is None:
            return None
        try:
            device = self.node.store.get(device_id)
        except RuntimeError:
            return None
        return None if device is None else device.name

    def _receive_dir(self) -> Path | None:
        if self.node is None:
            return None
        try:
            return self.node.transfers.receive_dir
        except RuntimeError:
            return None

    def _later(self, fn: Callable[[], None]) -> None:
        if self._muted:
            return
        if self._pending is not None:
            self._pending.append(fn)
        else:
            fn()

    def ready(self) -> None:
        """Đã in phần đầu: in các sự kiện đã giữ lại."""
        pending, self._pending = self._pending, None
        for fn in pending or ():
            fn()

    def after_stopping(self) -> None:
        if self.started:
            # Ctrl+C sau `Node.start` mà trước khi in xong phần đầu: in các sự kiện đã giữ lại ngay
            # sau “Đang dừng…”, để câu tạm dừng (và JSON `result`) của các lượt đóng trong
            # `node.close()` không bị mất.
            self.ready()
            return
        # Ctrl+C trong lúc `Node.start` (sau khi khôi phục, lúc mở cổng hay mDNS): `close()` không
        # tạm dừng lượt khôi phục (không có `SUSPENDED`), nên bỏ mọi sự kiện đang giữ và tới sau,
        # để không in câu “Tiếp tục nhận…” / `restored` mà không có kết quả. Đĩa giữ nguyên.
        self._pending = None
        self._muted = True

    def on_event(self, event: NodeEvent) -> None:
        if isinstance(event, DeviceConnected | DeviceDisconnected | ConnectFailed):
            self._later(functools.partial(_print_event, self.output, event))

    def on_transfer_event(self, update: TransferUpdate) -> None:
        self._later(functools.partial(self._handle, update))

    def _handle(self, update: TransferUpdate) -> None:
        if isinstance(update, DataUnreachable):
            self.printer.handle(update)
            return
        key = _key_of(update)
        if key is None or key.direction is not Direction.RECEIVE:
            return
        if isinstance(update, OfferReceived):
            self._offered.add(key)
            self._offer(update)
        elif isinstance(update, TransferResumed):
            if key in self._resumed or key in self._offered:
                return  # phòng thủ: mỗi lượt chỉ một sự kiện đầu
            self._resumed.add(key)
            self._quiet_reconnect.add(key)
            self.printer.handle(update)
        elif isinstance(update, TransferFinished):
            self._offered.discard(key)
            self._resumed.discard(key)
            self._quiet_reconnect.discard(key)
            self._finished(update)
        elif isinstance(update, TransferStatusChanged):
            if key not in self._offered and key not in self._resumed:
                # Kiểm chỗ trống / xếp hàng trước khi hỏi (`offer` là sự kiện đầu của lượt), hay lượt
                # khôi phục đã quá hạn nối lại (chỉ báo kết quả).
                return
            reconnecting = update.info.status is TransferStatus.RECONNECTING
            quiet = reconnecting and key in self._quiet_reconnect
            if not reconnecting:
                self._quiet_reconnect.discard(key)  # đã rời `reconnecting` ban đầu
            self.printer.status(update.info, quiet_reconnecting=quiet)
        else:
            self.printer.handle(update)

    def _offer(self, offer: OfferReceived) -> None:
        self.printer.note_files(offer.key, len(offer.files))
        receive_dir = self._receive_dir()
        self.output.event(
            "offer",
            **_transfer_fields(offer.key),
            device_name=offer.device_name,
            files=[{"name": n, "size": e.size} for n, e in zip(offer.names, offer.files, strict=False)],
            total_bytes=offer.total_bytes,
            auto_accepted=offer.auto_accepted,
            receive_dir=None if receive_dir is None else str(receive_dir),
        )
        if offer.auto_accepted:
            self.output.text(*offer_prompt_lines(offer, peer_name=offer.device_name, receive_dir=receive_dir))
            return
        self._queue.append((offer, time.perf_counter()))  # cùng đồng hồ với mốc của StdinReader
        if self._stdin_closed:
            self._reject_all()
        else:
            self._next()

    def on_stop(self) -> None:
        super().on_stop()
        self.output.close_question()  # lời hỏi đang mở sẽ được `close()` từ chối

    def _next(self) -> None:
        """Mở lời hỏi kế tiếp nếu đang không hỏi gì và chưa dừng."""
        if self.stopping or self._current is not None or not self._queue:
            return
        offer, emitted_at = self._queue.popleft()
        self._current = offer
        self._shown.add(offer.key)
        if self.output.json:
            self._shown_at = emitted_at
            return
        self._shown_at = time.perf_counter()
        lines = offer_prompt_lines(offer, peer_name=offer.device_name, receive_dir=self._receive_dir())
        self.output.text(*lines)
        self.output.ask(_ASK_RECEIVE)

    def _decide(self, offer: OfferReceived, accept: bool) -> None:
        if self.node is not None:
            self.node.transfers.decide(offer.key, accept)

    def feed(self, read_at: float, line: str | None) -> None:
        """Một dòng từ stdin (`None` = EOF)."""
        if line is None:
            self._stdin_closed = True
            self._reject_all()
            return
        offer = self._current
        if offer is None or read_at < self._shown_at:
            return  # không có lời hỏi, hoặc dòng gõ trước lúc hiện lời hỏi
        self.output.answered()
        answer = line.strip().casefold()
        if answer.isascii() and (answer in _YES or answer in _NO):
            self._current = None
            self._decide(offer, answer in _YES)
            self._next()
        elif not self.output.json:
            self.output.text("Hãy gõ c (nhận) hoặc k (từ chối).")
            self.output.ask(_ASK_RECEIVE)

    def _reject_all(self) -> None:
        """stdin đã đóng: từ chối lời hỏi đang mở và mọi lời hỏi đang chờ."""
        offers = [] if self._current is None else [self._current]
        offers += [offer for offer, _ in self._queue]
        self._current = None
        self._queue.clear()
        self.output.close_question()
        if not offers:
            return
        if not self._told_closed:
            self._told_closed = True
            self.output.text(_STDIN_CLOSED)
        for offer in offers:
            self._eof_rejected.add(offer.key)
            self._decide(offer, False)

    def _finished(self, finished: TransferFinished) -> None:
        key = finished.info.key
        reopen = False
        if self._current is not None and self._current.key == key:
            self._current = None  # lời hỏi tự đóng (máy gửi hủy…)
            self.output.close_question()
            reopen = True
        elif any(offer.key == key for offer, _ in self._queue):
            self._queue = deque((offer, at) for offer, at in self._queue if offer.key != key)
        shown = key in self._shown
        self._shown.discard(key)
        eof = key in self._eof_rejected
        self._eof_rejected.discard(key)
        lines: list[str] | None = None  # None: câu thường (“Đã từ chối.”…)
        if (
            finished.result is TransferResult.REJECTED_USER
            and not finished.by_peer
            and (eof or self.stopping)
        ):
            # Từ chối vì đầu vào đóng hay Ctrl+C (docstring lớp); JSON vẫn có `result` như cũ.
            if shown:
                lines = []
            else:
                n = len(finished.info.files)
                s = _peer_label(self._name_of(key.device_id), key.device_id)
                lines = [_rejected_no_answer(n, s) if eof else _rejected_stopping(n, s)]
        self.printer.finished(finished, lines=lines)
        if reopen:
            self._next()


async def run_receive(
    args: argparse.Namespace, lines: Lines, out: TextIO, err: TextIO, *, interrupts: Interrupts | None = None
) -> int:
    """`teleport receive`: nhận file tới khi Ctrl+C (mã 0); lỗi khởi động → 1, tham số sai → 2.

    Câu trả lời `[c/k]` đọc từ `lines` (không dùng khi `--yes`). `interrupts`: Ctrl+C (test gọi
    `press()`). Kết quả các lượt kết thúc trong lúc đóng node vẫn được in.
    """
    interrupts = interrupts if interrupts is not None else Interrupts()
    output = _Output(out, err, bool(getattr(args, "json", False)))
    session = _ReceiveSession(output)
    code = await _supervise(_receive_main(args, lines, output, session), session, output, interrupts)
    if code is not None:
        return code
    output.text("Đã dừng.")
    output.event("stopped")
    return 0


async def _receive_main(
    args: argparse.Namespace, lines: Lines, output: _Output, session: _ReceiveSession
) -> int:
    """Phần việc của `receive` (task con, bị hủy khi Ctrl+C); chỉ trả về khi lỗi khởi động."""
    if not _check_node_args(args, output):
        return 2
    auto_accept = bool(getattr(args, "yes", False))
    raw_dir = getattr(args, "dir", None)
    # Không có `--dir`: thư mục nhận đã lưu (giao diện), chưa có thì mặc định (QN1).
    receive_dir: Path | ReceiveDirChoice = (
        Path(os.path.abspath(os.path.expanduser(raw_dir))) if raw_dir else ReceiveDirChoice.SAVED
    )
    mdns = _mdns_options(args, advertise=True)
    node = Node(
        _config(args),
        name=getattr(args, "name", None),
        port=getattr(args, "port", None),
        host=getattr(args, "host", _ANY_HOST),
        accept_pairing=False,
        mdns=mdns,
        auto_connect=True,
        on_event=session.on_event,
        receive_dir=receive_dir,
        auto_accept=auto_accept,
        on_transfer_event=session.on_transfer_event,
    )
    session.node = node
    code = await _start_transfer_node(node, output)
    if code is not None:
        return code
    error = node.receive_dir_error
    root = node.transfers.receive_dir
    if error is not None or root is None:
        # Thư mục đã lưu không mở được: node vẫn chạy được, nhưng `receive` chỉ có việc nhận.
        if error is None:  # không xảy ra: có thư mục nhận hoặc có lỗi
            error = ReceiveDirUnavailable(default_receive_dir())
        message = receive_dir_error_message(error)
        output.error("receive_dir_error", message[0], extra=message[1:], path=str(error.path))
        return 1
    session.started = True  # cùng bước với lúc `start` trả về (không `await` xen giữa)
    addresses = await node.local_addresses()
    port = node.port
    discovery_error = node.discovery_error
    output.event(
        "receiving",
        name=node.name,
        device_id=node.identity.device_id,
        port=port,
        addresses=list(addresses),
        receive_dir=str(root),
        auto_accept=auto_accept,
        discovery=node.discovery_active,
        discovery_error=None if discovery_error is None else _error_text(discovery_error),
        visible=node.visible,
    )
    text = [
        "Teleport đang chờ nhận file.",
        f"  Tên:      {node.name}",
        f"  Mã máy:   {node.identity.device_id[:8]}",
        f"  Lưu vào:  {_printable(str(root))}",
    ]
    if auto_accept:
        text.append("Cảnh báo: đang tự nhận mọi file từ mọi thiết bị đã ghép đôi, không hỏi trước (`--yes`).")
    if not node.visible:
        text.append(_HIDDEN_WARNING)
    if mdns is not None and discovery_error is not None:
        text.append(
            f"Cảnh báo: chưa quảng bá được qua mDNS ({_error_text(discovery_error)}); máy khác vẫn gửi được "
            "bằng `teleport send … --address <IP của máy này>`."
        )
    if not node.store.devices():
        text.append(
            "Máy này chưa ghép đôi với thiết bị nào nên chưa nhận được file. Hãy ghép đôi trước: "
            "`teleport listen` trên một máy, `teleport pair` trên máy kia."
        )
    text.append("Nhấn Ctrl+C để dừng.")
    output.text(*text)
    session.ready()
    if auto_accept:
        await asyncio.Event().wait()  # chạy tới khi bị dừng; không đọc stdin
    while True:
        read_at, line = await lines.get()
        session.feed(read_at, line)


def _install_interrupts(loop: asyncio.AbstractEventLoop, interrupts: Interrupts) -> Callable[[], None]:
    """Gắn Ctrl+C (POSIX: SIGINT, SIGTERM; Windows: SIGINT, SIGBREAK) vào `interrupts.press` trên loop.

    Gọi trước `runner.run`; trả hàm khôi phục handler cũ, gọi sau khi đóng Runner. Không ở thread
    chính thì không gắn gì.
    """
    previous: list[tuple[int, Any]] = []
    if sys.platform == "win32":

        def handler(signum: int, frame: object) -> None:
            with contextlib.suppress(RuntimeError):  # loop đã đóng
                loop.call_soon_threadsafe(interrupts.press)

        for name in ("SIGINT", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            with contextlib.suppress(ValueError, OSError):  # không ở thread chính
                previous.append((sig, signal.signal(sig, handler)))
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                old = signal.getsignal(sig)
                loop.add_signal_handler(sig, interrupts.press)
            except (ValueError, RuntimeError, OSError):
                continue
            previous.append((sig, old))

    def restore() -> None:
        for sig, old in previous:
            with contextlib.suppress(ValueError, OSError, TypeError):
                signal.signal(sig, old)

    return restore


TransferRunFn = Callable[..., Awaitable[int]]


async def _transfer_main(
    args: argparse.Namespace, run: TransferRunFn, interrupts: Interrupts, *, stdin: bool
) -> int:
    lines: Lines = asyncio.Queue()
    if stdin:
        StdinReader(asyncio.get_running_loop(), lines).start()
    return await run(args, lines, sys.stdout, sys.stderr, interrupts=interrupts)


def _run_transfer_command(args: argparse.Namespace, run: TransferRunFn, *, stdin: bool) -> int:
    """Chạy `send` / `receive` trong event loop riêng, Ctrl+C qua `Interrupts` (docstring module)."""
    interrupts = Interrupts()
    restore: Callable[[], None] = _no_restore
    try:
        with asyncio.Runner() as runner:
            restore = _install_interrupts(runner.get_loop(), interrupts)
            return runner.run(_transfer_main(args, run, interrupts, stdin=stdin))
    finally:
        restore()


def _no_restore() -> None:
    return None


def cmd_send(args: argparse.Namespace) -> int:
    return _run_transfer_command(args, run_send, stdin=False)


def cmd_receive(args: argparse.Namespace) -> int:
    # --yes không đọc stdin: chạy nền trên POSIX mà đọc stdin thì bị SIGTTIN dừng tiến trình.
    return _run_transfer_command(args, run_receive, stdin=not args.yes)


# ---- unpair --------------------------------------------------------------------------------


def _candidates(devices: Sequence[TrustedDevice | DeviceView]) -> list[dict[str, str]]:
    return [{"device_id": d.device_id, "name": d.name} for d in devices]


def cmd_unpair(args: argparse.Namespace) -> int:
    output = _Output(sys.stdout, sys.stderr, args.json)
    query = args.device
    directory = _config(args)
    try:
        device = unpair_offline(directory, query)
    except OSError as e:
        _config_dir_error(output, directory, e)
        return 1
    except NodeLockedError:
        output.error("node_locked", "Teleport đang chạy với thư mục cấu hình này.", extra=[_NODE_LOCKED_HINT])
        return 1
    except TrustStoreError as e:
        output.error("trust_store_error", str(e))
        return 1
    except (DeviceNotFound, AmbiguousDevice) as e:
        _trusted_lookup_error(output, query, e)
        return 1
    if output.json:
        obj = {"time": _utc_now(), "removed": True, "device_id": device.device_id, "name": device.name}
        print(json.dumps(obj, ensure_ascii=False), flush=True)
    else:
        print(f"Đã hủy ghép đôi với {_name_label(device.name)} ({device.device_id[:8]}).", flush=True)
    return 0


# ---- Tham số -------------------------------------------------------------------------------


def _port_type(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"cổng phải là số nguyên 0–65535: {text!r}") from None
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError(f"cổng phải là số nguyên 0–65535: {text!r}")
    return value


def _add_node_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="in sự kiện dạng JSON Lines")
    parser.add_argument(
        "--name", help="tên thiết bị cho lần chạy này (mặc định: tên đã lưu, chưa có thì tên máy)"
    )
    # Ẩn: chỉ để test bind 127.0.0.1 và cổng 0 (tránh hộp thoại tường lửa Windows).
    parser.add_argument("--host", default=_ANY_HOST, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=_port_type, default=None, help=argparse.SUPPRESS)
    # Ẩn: chỉ duyệt/quảng bá mDNS trên các card này (test dùng 127.0.0.1).
    parser.add_argument("--mdns-interface", action="append", type=_ipv4_type, help=argparse.SUPPRESS)


def _ipv4_type(text: str) -> str:
    if not _valid_host(text):
        raise argparse.ArgumentTypeError(f"phải là địa chỉ IPv4 dạng chấm: {text!r}")
    return text


def _timeout_type(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"thời gian phải là số giây: {text!r}") from None
    if not math.isfinite(value) or not 0 < value <= MAX_SCAN_TIMEOUT:
        raise argparse.ArgumentTypeError(
            f"thời gian phải trong khoảng (0, {MAX_SCAN_TIMEOUT:g}] giây: {text!r}"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="teleport",
        description="Chuyển file và clipboard trong mạng LAN, không qua cloud.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config-dir",
        type=Path,
        help=f"thư mục cấu hình (mặc định theo hệ điều hành, hoặc biến môi trường {ENV_HOME})",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<lệnh>")
    sub.add_parser("identity", help="hiện mã thiết bị và fingerprint của máy này").set_defaults(
        handler=cmd_identity
    )

    list_ = sub.add_parser("list", help="liệt kê các máy Teleport trong mạng")
    list_.add_argument(
        "--timeout",
        type=_timeout_type,
        default=SCAN_TIMEOUT,
        metavar="GIÂY",
        help=f"thời gian tìm (mặc định {SCAN_TIMEOUT:g} giây)",
    )
    list_.add_argument("--json", action="store_true", help="in kết quả dạng JSON")
    list_.add_argument("--mdns-interface", action="append", type=_ipv4_type, help=argparse.SUPPRESS)
    list_.set_defaults(handler=cmd_list)

    listen = sub.add_parser("listen", help="chờ ghép đôi và giữ kết nối với các máy đã ghép đôi")
    _add_node_options(listen)
    # Ẩn: địa chỉ quảng bá cố định (test), không theo dõi đổi địa chỉ.
    listen.add_argument("--advertise-address", action="append", type=_ipv4_type, help=argparse.SUPPRESS)
    listen.set_defaults(handler=cmd_listen)

    pair = sub.add_parser("pair", help="ghép đôi với máy khác theo tên, mã thiết bị hoặc địa chỉ IP")
    pair.add_argument(
        "address",
        metavar="<tên | tiền tố mã | ip[:cổng]>",
        help="máy kia như `teleport list` hiện, hoặc địa chỉ IP, ví dụ 192.168.1.5",
    )
    _add_node_options(pair)
    pair.set_defaults(handler=cmd_pair)

    send = sub.add_parser("send", help="gửi file tới một thiết bị đã ghép đôi")
    send.add_argument(
        "files", nargs="+", metavar="<file>", help=f"các file cần gửi (tối đa {MAX_OFFER_FILES})"
    )
    send.add_argument(
        "--to", required=True, metavar="<thiết bị>", help="tên hoặc tiền tố mã thiết bị đã ghép đôi"
    )
    send.add_argument(
        "--address", metavar="<ip[:cổng]>", help="địa chỉ của máy nhận, khi mạng chặn mDNS (vẫn cần --to)"
    )
    send.add_argument(
        "--limit-rate",
        metavar="<tốc độ>",
        help=(
            "giới hạn tốc độ gửi (byte/giây, hệ nhị phân), ví dụ 20M hoặc 512K; tối thiểu 64K "
            "(mặc định: theo cài đặt)"
        ),
    )
    _add_node_options(send)
    send.set_defaults(handler=cmd_send)

    receive = sub.add_parser("receive", help="nhận file từ các thiết bị đã ghép đôi")
    receive.add_argument(
        "--dir",
        metavar="<thư mục>",
        help=(
            "thư mục lưu file nhận (mặc định: thư mục đã lưu trong cài đặt, chưa có thì Teleport "
            "trong thư mục Tải về)"
        ),
    )
    receive.add_argument(
        "--yes", action="store_true", help="tự nhận mọi file từ mọi thiết bị đã ghép đôi, không hỏi"
    )
    _add_node_options(receive)
    receive.add_argument("--advertise-address", action="append", type=_ipv4_type, help=argparse.SUPPRESS)
    receive.set_defaults(handler=cmd_receive)

    unpair = sub.add_parser("unpair", help="hủy ghép đôi với một thiết bị (khi Teleport không chạy)")
    unpair.add_argument("device", metavar="<thiết bị>", help="tên hoặc tiền tố mã thiết bị (≥ 4 ký tự)")
    unpair.add_argument("--json", action="store_true", help="in kết quả dạng JSON")
    unpair.set_defaults(handler=cmd_unpair)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Ép UTF-8 để tiếng Việt hiển thị đúng cả khi đầu ra bị chuyển hướng (pipe).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s"
    )
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except IdentityError as e:
        # Lỗi người dùng tự xử lý được: in thông báo, không in traceback.
        print(f"Lỗi: {e}", file=sys.stderr)
        return 1
