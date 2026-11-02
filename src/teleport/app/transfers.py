"""Quản lý lượt truyền file của một node: chạy `core.transfer.TransferEngine` trên kết nối thật.

`TransferManager` (chỉ `Node` tạo, lấy qua `node.transfers`) thực thi hành động của **một**
`TransferEngine` cho cả node theo hợp đồng ở docstring `core/transfer.py`; mọi chính sách (kiểm
`data_open`, `seq`, lịch thử lại, nhịp `fsync`, luật khối sai, bia mộ, chờ nối lại) nằm ở engine.
Ở đây chỉ có I/O:

- **Gọi engine** (`_call`): đọc `now = loop.time()` ngay lúc gọi (kể cả lời gọi bị hoãn, kết quả
  giao sau, `call_soon` của tự nhận), rồi thực hiện danh sách hành động đồng bộ, đúng thứ tự, không
  `await` xen giữa. **Không gọi engine lồng nhau:** lời gọi phát sinh trong lúc đang thực hiện (kể
  cả từ callback `on_transfer_event`) xếp vào hàng `_deferred`, chạy sau khi danh sách hiện tại
  xong. Engine ném lỗi thì chỉ ghi log; một hành động ném lỗi thì ghi log rồi vẫn chạy các hành
  động sau.
- **Kết nối điều khiển:** `Node` báo `control_up` / `control_lost` theo `LinkUp`, `LinkSwitched`,
  `LinkDown`, và giao message truyền file (`on_message`). `SendMessage` đi qua hàng gửi FIFO của
  kết nối hiện tại (`_Outbox`), có trần `CONTROL_SEND_QUEUE_MAX` message: tràn thì cắt kết nối đó
  (máy kia gửi liên tục mà không đọc), thành mất kết nối điều khiển và chờ nối lại như thường.
- **Kết nối dữ liệu:** `OpenData` mở bằng `open_data` (một địa chỉ, một lần thử); phía server,
  `serve_data` báo `incoming_data` trước `await` đầu tiên rồi giữ handler tới khi kết nối xong.
  Mỗi `SendBlocks` / `ReceiveBlocks` là một task; task kết thúc thì cắt kết nối (trừ lần đóng gọn
  khi bên gửi đã ghi hết khối). Bên nhận ngừng đọc khung khi đã có `WRITE_QUEUE_BLOCKS` khối chờ
  ghi (protocol §4.3; cận gửi lại của mvp N4).
- **Đĩa:** mọi thao tác chạm hệ file (`app.storage`, `app.sources`) đi qua `DiskExecutor` bằng
  `submit` (không `run`, để không mất handle khi bị hủy); mỗi lượt nhận có một hàng FIFO đĩa
  (`_DiskLane`) với luật `RemoveTemp` của hợp đồng (mục 5). Việc quá hạn vẫn chạy trong thread:
  kết quả tới muộn được dọn sau `DiskJob.settled()` (thư mục tạm tạo muộn bị xóa, file nguồn mở
  muộn bị đóng). Băm payload nhận dùng `asyncio.to_thread` (chỉ tốn CPU). Khi node đóng, task
  đĩa không bao giờ bị hủy (kể cả `abort_now`): chúng chờ việc đang chạy rồi chạy bước dọn; thư
  mục nhận đóng khi mọi việc dùng nó đã `settled()`, nếu cần thì ở **đuôi đĩa** chạy nền sau khi
  `close()` / `abort_now()` trả về (`_shutdown_disk`).
- **Giữ địa chỉ:** thiết bị còn lượt chưa kết thúc được `hold` ở `core.links` (nối lại theo lịch
  kể cả khi mDNS báo máy đi, protocol §6.1, §6.2).
- **Giới hạn tốc độ:** một `TokenBucket` chung cho mọi lượt gửi, áp theo từng đoạn 64 KiB
  (`core.ratelimit`); khi có giới hạn, tối đa `MAX_LIMITED_SENDS` lượt gửi chạy cùng lúc để mỗi
  lần chờ một đoạn ngắn hơn hạn chờ đọc của bên nhận. Cùng móc đó đếm `payload_sent` của từng
  lượt gửi (`TransferFinished`).
- **Khôi phục** (`restore`, `Node.start` gọi đúng một lần trước khi mở cổng): đọc
  `tombstones.json` (`app.tombstones`, hạn `DISK_OP_TIMEOUT`) và quét thư mục nhận
  (`scan_temps`, hạn `DISK_SYNC_TIMEOUT`); mỗi máy gửi chỉ giữ lượt RUNNING có hoạt động cuối
  gần nhất (bằng nhau: `transfer_id` lớn hơn), lượt RUNNING còn lại bị xóa (`discard_temp`,
  chạy nền sau các lần mở lại, chỉ khi `engine.restore` đã nạp bia mộ `expired` của chúng;
  `cleanup_temps` bỏ qua chúng tới khi xóa xong, vì dọn tạm đang giữ một thư mục thì
  `discard_temp` bỏ qua thư mục đó và không thử lại) kèm bia mộ `expired` chưa gửi; lượt DONE
  thành `RestoredDone`.
  Mở lại song song (`open_for_resume`), mỗi lượt có `stop` và hạn riêng, cả bước có hạn tổng;
  lượt quá hạn hay lỗi bị bỏ, để nguyên trên đĩa. Rồi trong **một khối đồng bộ**: dựng hàng đĩa
  cho lượt mở được (trước khi thực thi hành động), `engine.restore` (lời gọi engine đầu tiên, kể
  cả khi không có thư mục nhận), `TransferResumed` cho lượt còn trong hạn nối lại, thực thi hành
  động.
- **Tạm dừng** (`begin_close`): `engine.suspend_receiving` → `SuspendTemp`: hàng đĩa bỏ
  `Finalize` / `Reread` chưa bắt đầu, chạy nốt các thao tác đứng trước khác (để `MARK` bền), rồi
  chỉ đóng handle (`close_temp`); không `cancel` trên dây. `Finalize` đang chạy thì chạy tới cùng
  (giới hạn đã biết, `_close_lane`). `RemoveTemp(keep_record=True)` của lượt DONE giữ `transfer.json`.
- **Bia mộ:** `TombstonesChanged` chỉ đánh dấu và hẹn (`call_soon`, hay `call_later` cho đủ
  `TOMBSTONE_MIN_INTERVAL` từ lần ghi trước); lúc chạy mới chụp `export_tombstones` rồi ghi
  `tombstones.json` qua executor (mã hóa trong thread). Tối đa một lần ghi tại một thời điểm, và
  lần sau chỉ bắt đầu khi việc trước đã `settled` (tên `.tmp` cố định), kể cả khi quá hạn.
  `close()` xả ảnh chụp cuối tối đa `TOMBSTONE_FLUSH_TIMEOUT`; `abort_now()` không xả.
- **Lịch sử** (mvp F5, `app/history.py`): mỗi `TransferEnded` trừ `SUSPENDED` thành một mục
  (`_record_history`, trước `_forget_transfer` và trước `_emit`); nạp song song với bia mộ trong
  `restore`, xả song song với bia mộ trong `close()` cùng hạn `TOMBSTONE_FLUSH_TIMEOUT`.
- **Dọn tạm** (`cleanup_temps`, `Node` hẹn giờ mỗi `CLEANUP_INTERVAL`): `skip` là lượt nhận engine
  còn giữ và hàng đĩa còn sống, chụp đồng bộ ngay trước khi giao việc; ngưỡng theo
  `set_temp_retention` (cài đặt), chưa đặt thì `storage.TEMP_RETENTION`.
- **Nhận hay không** (`engine.receiving`): có thư mục nhận, không `pause_receiving`, chưa đóng; chỉ
  gán thuộc tính, không gọi engine. Hỏi trước khi nhận theo thiết bị (`ask_before_receive`, đọc lúc
  `AskUser`); `auto_accept` (`--yes`) tự nhận mọi thiết bị.
- **Đổi thư mục nhận** (`replace_receive_dir`, chỉ khi `receive_dir_busy()` sai): thư mục cũ
  thôi dùng và đóng khi không còn ai dùng (`_close_retired`). Mọi việc đĩa chụp thư mục nhận đồng
  bộ lúc giao việc (hàng đĩa giữ `lane.rd`; dọn tạm, kiểm chỗ trống, `discard_temp`, đóng handle
  của khôi phục nhận `rd` tường minh), đăng ký là người dùng của nó (`_DirUse`), không đọc lại
  `_receive_dir` sau `await`. `offer` chưa nhận không làm bận: sau khi đổi, `engine.recheck_space`
  kiểm lại chúng trên thư mục mới, và `space_checked` mang `check_id` của `CheckSpace` để kết quả
  kiểm trên thư mục cũ bị bỏ.

`preview_sources(paths)` kiểm trước các file sẽ gửi mà không cần node (cùng lỗi như `send`), để
CLI báo lỗi file trước khi lấy `node.lock` hay đụng mạng.

Sự kiện cho giao diện / CLI: một callback `on_transfer_event` (`TransferUpdate`), gọi đồng bộ trên
loop theo thứ tự engine báo; vẫn phát trong lúc `close()`, hết phát khi `close()` trả về. Kết quả
cuối của mỗi lượt là `TransferResult` (mã, không có câu chữ: câu chữ ở `cli.py` / `ui`).

Log (mvp N9): không bao giờ ghi tên hay đường dẫn file; chỉ `transfer_id[:8]`, `file_index`,
`device_id[:8]`, loại lỗi và `errno` (`OSError` có thể mang đường dẫn trong `str(e)`, nên không
ghi `str(e)` hay traceback của nó).

Seam cho test (biến cấp module, đọc lúc dùng): các hằng dưới đây, `open_data`, `uuid4`,
`_wall_time` (giờ tường: tuổi khi khôi phục, mốc `at` của bia mộ, `cleanup`); module `sources`
được gọi qua thuộc tính (`sources.prepare_sources`, `sources.SourceReader`,
`sources.check_source`), `tombstones.load` / `tombstones.save` cũng vậy, như `history.load` /
`history.save` / `history._read_limited` (gọi trong `app/history.py`); `storage.TEMP_RETENTION`,
`diskio.DISK_THREADS`, `core.transfer.RECONNECT_GRACE` đọc lúc dùng.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import logging
import math
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from teleport.app import diskio, sources, storage, tombstones
from teleport.app.diskio import DiskExecutor, DiskJob, DiskTimeout
from teleport.app.history import HistoryStore
from teleport.app.sources import SourceChanged, SourceError, SourceErrorKind, SourceFile, SourceReader
from teleport.app.storage import (
    NotResumableError,
    PartFile,
    ReceiveDir,
    ReceiveDirMissingError,
    RereadStopped,
    ResumeHandle,
    ResumeMode,
    StorageError,
    TempExistsError,
    TempKind,
    TempScan,
    TransferTemp,
)
from teleport.core import ratelimit
from teleport.core import transfer as core_transfer
from teleport.core.blocks import DIGEST_SIZE, BlockError
from teleport.core.history import HistoryEntry, HistoryError, entry_from_info
from teleport.core.merkle import merkle_root
from teleport.core.messages import (
    Accept,
    Cancel,
    CancelReason,
    Complete,
    DataOpen,
    FileEntry,
    Hello,
    Offer,
    Reject,
    RejectReason,
    Resume,
    Verified,
    validate_device_id,
)
from teleport.core.ratelimit import TokenBucket
from teleport.core.resume_state import TombstoneRecord, TransferRecord
from teleport.core.transfer import (
    AskUser,
    CheckSource,
    CheckSpace,
    ClearBlocks,
    CloseData,
    CreateTemp,
    DataUnreachable,
    Direction,
    DiskOp,
    FailureDetail,
    FileVerified,
    Finalize,
    OpenData,
    OpenPart,
    Outcome,
    ReceiveBlocks,
    RemoveTemp,
    Report,
    Reread,
    RestoredDone,
    RestoredReceive,
    RestoredTombstone,
    SendBlocks,
    SendMessage,
    StatusChanged,
    SuspendTemp,
    SyncPart,
    TombstonesChanged,
    TransferAction,
    TransferEnded,
    TransferEngine,
    TransferEvent,
    TransferIdInUse,
    TransferInfo,
    TransferKey,
    TransferMessage,
    TransferStatus,
    WriteBlock,
)
from teleport.net.connection import (
    Connection,
    ConnectionLostError,
    IdentityMismatch,
    VersionMismatch,
    open_data,
)
from teleport.trust.identity import Identity
from teleport.trust.store import TrustStore

__all__ = [
    "MIN_RATE_LIMIT",
    "DataUnreachable",
    "Direction",
    "FileDone",
    "FileEntry",
    "OfferReceived",
    "ReceiveDirBusy",
    "SourceError",
    "SourceErrorKind",
    "SourceFile",
    "TransferFinished",
    "TransferInfo",
    "TransferKey",
    "TransferManager",
    "TransferProgress",
    "TransferResult",
    "TransferResumed",
    "TransferStatus",
    "TransferStatusChanged",
    "TransferUpdate",
    "preview_sources",
]

# architecture §5 (bảng số của truyền file). Đọc lúc dùng: test vá bằng monkeypatch.
# Hạn đĩa: danh sách đủ các thao tác ở bảng architecture §5.
DISK_OP_TIMEOUT = 60.0  # một thao tác đĩa (tạo thư mục tạm, ghi/đọc khối, đọc/ghi `tombstones.json`…)
DISK_SYNC_TIMEOUT = 120.0  # `fsync`, `finalize`, đọc lại; quét, mở lại mỗi lượt khi khôi phục; dọn tạm
REREAD_BLOCK_TIMEOUT = 1.0  # đọc lại: cộng thêm mỗi khối
CONTROL_SEND_QUEUE_MAX = 4096  # message chờ gửi trên một kết nối điều khiển; tràn → cắt kết nối đó
CANCEL_FLUSH_TIMEOUT = 0.5  # `Node.close`: chờ đẩy hết `cancel` ra kết nối điều khiển
CLOSE_DISK_WAIT = 2.0  # `Node.close`: chờ các hàng đĩa xong `RemoveTemp` / `SuspendTemp`
TOMBSTONE_FLUSH_TIMEOUT = 2.0  # `Node.close`: chờ ghi nốt `tombstones.json`
TOMBSTONE_MIN_INTERVAL = 1.0  # giây tối thiểu giữa hai lần ghi `tombstones.json`
CLEANUP_INTERVAL = 24 * 3600.0  # `Node`: nhịp hẹn giờ dọn tạm (`cleanup_temps`)
MAX_LIMITED_SENDS = 8  # có giới hạn tốc độ: số `SendBlocks` chạy cùng lúc
MIN_RATE_LIMIT = ratelimit.CHUNK_SIZE  # byte/giây: mỗi lần chờ một đoạn ≤ 1 s
PROGRESS_INTERVAL = 1.0  # giây giữa hai lần báo tiến độ
SPEED_WINDOW = 5.0  # tốc độ tính trên các mẫu trong 5 s gần nhất
WRITE_QUEUE_BLOCKS = 8  # protocol §4.3: khối đã nhận chờ ghi đĩa tối đa

_TASK_NAME = "teleport.node"

# Đuôi đĩa (`TransferManager._shutdown_disk`): chu kỳ kiểm lại thread đĩa còn bận (`wait_idle` buộc
# có hạn); không phải hạn chờ, đuôi chờ tới khi mọi thread xong.
_TAIL_IDLE_POLL = 1.0

# Tham chiếu mạnh tới task đuôi đĩa và task đĩa còn chạy sau khi executor đã dừng: `Node` có thể đã
# bỏ `TransferManager` (`_abort_start`), mà event loop chỉ giữ tham chiếu yếu tới task.
_detached_tasks: set[asyncio.Task[Any]] = set()


def _keep_detached(task: asyncio.Task[Any]) -> None:
    """Giữ `task` tới khi xong; dọn task đã xong hay thuộc loop đã đóng (callback không chạy nữa)."""
    stale = [t for t in _detached_tasks if t.done() or t.get_loop().is_closed()]
    _detached_tasks.difference_update(stale)
    if task in _detached_tasks or task.done():
        return
    _detached_tasks.add(task)
    task.add_done_callback(_detached_tasks.discard)


# Giờ tường (seam cho test, đọc lúc dùng): tuổi khi khôi phục, mốc `at` của bia mộ, `cleanup`.
_wall_time = time.time

_TRANSFER_MESSAGE_TYPES = (Offer, Accept, Reject, Resume, Complete, Verified, Cancel)

# Lời gọi engine bị hoãn (phương thức, đối số, đối số từ khóa); `now` thêm lúc thật sự gọi.
_Deferred = tuple[Callable[..., list[TransferAction]], tuple[Any, ...], dict[str, Any]]

log = logging.getLogger(__name__)


# ---- Kết quả và sự kiện cho giao diện ------------------------------------------------------


class TransferResult(StrEnum):
    """Kết quả cuối của một lượt (`TransferFinished.result`)."""

    DONE = "done"
    REJECTED_USER = "rejected_user"
    REJECTED_NO_SPACE = "rejected_no_space"
    REJECTED_FILE_TOO_LARGE = "rejected_file_too_large"
    REJECTED_BUSY = "rejected_busy"
    REJECTED_NOT_RECEIVING = "rejected_not_receiving"
    REJECTED_OTHER = "rejected_other"
    UNPAIRED = "unpaired"  # máy này hủy ghép đôi khi lượt chưa kết thúc
    SUSPENDED = "suspended"  # lượt nhận tạm dừng khi node đóng có trật tự; khôi phục ở lần chạy sau
    CANCELLED_USER = "cancelled_user"
    SOURCE_CHANGED = "source_changed"
    EXPIRED = "expired"  # mất kết nối điều khiển quá `RECONNECT_GRACE` (24 h, protocol §6.2)
    DISK_FAILED = "disk_failed"
    TEMP_EXISTS = "temp_exists"  # thư mục tạm của lượt đã có sẵn mà không dùng tiếp được
    RECEIVE_DIR_MISSING = "receive_dir_missing"  # thư mục nhận đã mất và không tạo lại được
    CORRUPT = "corrupt"  # khối sai quá trần, hoặc đọc lại / Merkle sai quá trần
    PROTOCOL_ERROR = "protocol_error"
    SOURCE_READ_FAILED = "source_read_failed"
    PEER_ERROR = "peer_error"  # máy kia gửi `cancel{error}`
    UNKNOWN_TRANSFER = "unknown_transfer"  # máy kia không biết lượt này (ví dụ đã khởi động lại)
    CANCELLED_OTHER = "cancelled_other"


@dataclass(frozen=True, slots=True)
class OfferReceived:
    """Có `offer` cần trả lời (`decide`), hoặc đã tự nhận (`auto_accepted`)."""

    key: TransferKey
    device_name: str | None  # tên trong trusted.json, chưa qua `display_name`
    files: tuple[FileEntry, ...]
    names: tuple[str, ...]  # đã làm sạch và khử trùng trong `offer`
    total_bytes: int
    auto_accepted: bool


@dataclass(frozen=True, slots=True)
class TransferStatusChanged:
    info: TransferInfo


@dataclass(frozen=True, slots=True)
class TransferProgress:
    """Tiến độ một lượt, xét mỗi `PROGRESS_INTERVAL`.

    Phát khi `shown_bytes` hoặc `info.done_bytes` đổi so với lần phát trước của lượt (lần đầu thấy
    lượt luôn phát), hoặc mỗi nhịp khi lượt đã được phát ít nhất một lần và đang TRANSFERRING /
    RECONNECTING, kể cả khi đứng yên (để giao diện biết dữ liệu ngừng chảy). QUEUED / WAITING /
    VERIFYING không đổi thì không phát.

    - `info.done_bytes` vẫn là byte đã bền (`TransferInfo`); CLI, lịch sử và resume dùng nó.
    - `shown_bytes`: byte để hiển thị, `min(total, max(lần trước, done_bytes + unsynced_bytes))`;
      không bao giờ giảm trong một lượt, 0 ≤ `shown_bytes` ≤ `total_bytes`.
    - `idle_seconds`: số giây từ nhịp cuối mà `done_bytes + unsynced_bytes` (chưa kẹp) khác nhịp
      trước, tăng hay giảm đều tính (lần đầu thấy lượt là mốc); 0.0 nếu vừa đổi ở nhịp này. Nên dữ
      liệu chảy lại cho byte đã tính (gửi lại khối sau nối lại) không bị báo là đứng yên dù
      `shown_bytes` chưa tăng.
    - `bytes_per_second`: theo `shown_bytes` trên các mẫu trong `SPEED_WINDOW` (đứng yên quá cửa
      sổ thì 0.0); `eta` (giây) = (total − shown) / tốc độ, None khi tốc độ bằng 0.
    """

    info: TransferInfo
    bytes_per_second: float
    eta: float | None
    shown_bytes: int
    idle_seconds: float


@dataclass(frozen=True, slots=True)
class FileDone:
    """Một file đã xong. `path`: bên nhận là đường dẫn file cuối; bên gửi là None."""

    key: TransferKey
    file_index: int
    name: str
    path: Path | None


@dataclass(frozen=True, slots=True)
class TransferFinished:
    """Lượt kết thúc (đúng một lần mỗi lượt); `info` là bản chụp cuối.

    `payload_sent` (bên gửi): tổng byte payload đã giao cho kết nối dữ liệu qua `write_block`,
    mọi file, mọi kết nối, kể cả khung ghi dở, không tính header. Là cận trên: mỗi lần đứt có thể
    tính thừa tối đa một đoạn `_SEND_CHUNK` của `teleport.net.connection` (đếm trước khi ghi đoạn
    đó). Bên nhận: 0.
    """

    info: TransferInfo
    result: TransferResult
    by_peer: bool
    reason: str | None
    file_index: int | None
    reject: Reject | None
    payload_sent: int = 0


@dataclass(frozen=True, slots=True)
class TransferResumed:
    """Lượt nhận dở được khôi phục khi khởi động; đang chờ máy gửi nối lại."""

    info: TransferInfo


TransferUpdate = (
    OfferReceived
    | TransferStatusChanged
    | TransferProgress
    | FileDone
    | TransferFinished
    | TransferResumed
    | DataUnreachable
)

_REJECT_RESULTS: dict[str, TransferResult] = {
    RejectReason.USER: TransferResult.REJECTED_USER,
    RejectReason.NO_SPACE: TransferResult.REJECTED_NO_SPACE,
    RejectReason.FILE_TOO_LARGE: TransferResult.REJECTED_FILE_TOO_LARGE,
    RejectReason.BUSY: TransferResult.REJECTED_BUSY,
    RejectReason.NOT_RECEIVING: TransferResult.REJECTED_NOT_RECEIVING,
}

_ERROR_RESULTS: dict[FailureDetail | None, TransferResult] = {
    FailureDetail.DISK: TransferResult.DISK_FAILED,
    FailureDetail.TEMP_EXISTS: TransferResult.TEMP_EXISTS,
    FailureDetail.RECEIVE_DIR_MISSING: TransferResult.RECEIVE_DIR_MISSING,
    FailureDetail.CORRUPT_BLOCKS: TransferResult.CORRUPT,
    FailureDetail.VERIFY_FAILED: TransferResult.CORRUPT,
    FailureDetail.PROTOCOL: TransferResult.PROTOCOL_ERROR,
    FailureDetail.SOURCE_READ: TransferResult.SOURCE_READ_FAILED,
}


def _result_of(ended: TransferEnded, unpaired: bool) -> TransferResult:
    """`TransferEnded` → `TransferResult`. Lượt bị hủy vì hủy ghép đôi xét trước mọi thứ khác."""
    if unpaired:
        return TransferResult.UNPAIRED
    if ended.outcome is Outcome.SUSPENDED:
        return TransferResult.SUSPENDED
    if ended.outcome is Outcome.DONE:
        return TransferResult.DONE
    reason = ended.reason or ""
    if ended.outcome is Outcome.REJECTED:
        return _REJECT_RESULTS.get(reason, TransferResult.REJECTED_OTHER)
    if reason == CancelReason.USER:
        return TransferResult.CANCELLED_USER
    if reason == CancelReason.SOURCE_CHANGED:
        return TransferResult.SOURCE_CHANGED
    if reason == CancelReason.EXPIRED:
        return TransferResult.EXPIRED
    if reason == CancelReason.ERROR:
        if ended.by_peer:
            return TransferResult.PEER_ERROR
        return _ERROR_RESULTS.get(ended.detail, TransferResult.CANCELLED_OTHER)
    if reason == CancelReason.UNKNOWN_TRANSFER and ended.by_peer:
        return TransferResult.UNKNOWN_TRANSFER
    return TransferResult.CANCELLED_OTHER


async def preview_sources(paths: Sequence[str | os.PathLike[str]]) -> list[SourceFile]:
    """Kiểm các file sẽ gửi như `TransferManager.send` (`sources.prepare_sources`), không cần node.

    Chạy trên một `DiskExecutor` một thread dùng một lần (thread daemon), không hạn (ổ mạng có
    thể treo: bên gọi hủy được). Lỗi như `send`: `SourceError`, ValueError (0 hoặc quá
    `MAX_OFFER_FILES` file, một file chọn hai lần), TypeError. Bị hủy → bỏ việc nếu chưa chạy;
    thread đang chạy thì chạy nốt rồi tự thoát. Không giữ handle nào sau khi trả về.
    """
    executor = DiskExecutor(1, name="teleport.preview")
    try:
        job = executor.submit(sources.prepare_sources, paths)
        try:
            return await job.result(None)
        except asyncio.CancelledError:
            job.cancel()
            raise
    finally:
        executor.shutdown()


# ---- Việc đĩa --------------------------------------------------------------------------------


class ReceiveDirBusy(Exception):
    """Không đổi được thư mục nhận: còn lượt nhận đã chấp nhận (kể cả chờ nối lại, lượt khôi
    phục), hàng đĩa còn sống, hay lượt thừa của khôi phục đang được xóa. `offer` chưa nhận
    (xếp hàng, kiểm chỗ trống, chờ hỏi) không làm bận."""


class _JobDropped(Exception):
    """Việc đĩa bị `DiskExecutor.shutdown()` bỏ trước khi chạy (không phải task này bị hủy)."""


async def _job_result[T](job: DiskJob[T], timeout: float | None) -> T:
    """`job.result(timeout)`; việc bị bỏ khi shutdown → `_JobDropped` thay cho CancelledError.

    Phân biệt bằng trạng thái của task đang chờ (`cancelling()`), không dựa vào CancelledError.
    """
    try:
        return await job.result(timeout)
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if (task is not None and task.cancelling()) or job.started:
            raise
        raise _JobDropped("việc đĩa bị bỏ khi đóng") from None


async def _late_result[T](job: DiskJob[T]) -> T | None:
    """Kết quả của một việc đã `done` (kể cả việc đã quá hạn); lỗi hay bị bỏ → None."""
    try:
        return await job.result(None)
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise
        return None
    except Exception:
        return None


def _sha256(data: bytearray) -> bytes:
    return hashlib.sha256(data).digest()


def _reread_compare(
    part: PartFile, leaves: bytearray, stop: threading.Event
) -> tuple[list[int], bytes | None]:
    """(thread) Đọc lại `.part`, so hash từng khối với `leaves` → `(bad, root)` cho `reread_done`.

    `leaves` là bytearray của engine: chỉ đọc (engine không sửa nó lúc VERIFYING). Lượt khôi phục
    ở `VERIFY_TARGET` (đọc file đích thay `.part`) mà file đích không khớp: bỏ file đích (để
    nguyên trên đĩa, `PartFile.drop_target`), mọi khối là sai, nhận lại vào `.part` mới và tên mới.
    Lỗi (kể cả của `drop_target`) bay ra: bên gọi báo `storage_failed(REREAD)`.
    """
    digests = part.reread(stop=stop)
    if digests == leaves:
        return [], merkle_root(leaves)
    n = len(leaves) // DIGEST_SIZE
    if part.mode is ResumeMode.VERIFY_TARGET:
        part.drop_target()
        return list(range(n)), None
    have, want = memoryview(digests), memoryview(leaves)
    bad = [
        i
        for i in range(n)
        if have[i * DIGEST_SIZE : (i + 1) * DIGEST_SIZE] != want[i * DIGEST_SIZE : (i + 1) * DIGEST_SIZE]
    ]
    if not bad:  # phòng thủ: độ dài khác nhau mà mọi khối so được đều khớp
        bad = list(range(n))
    return bad, None


def _encode_and_save(config_dir: Path, items: tuple[RestoredTombstone, ...], wall_now: float) -> None:
    """(thread) Đổi tuổi ra mốc giờ tường, mã hóa và ghi `tombstones.json` (qua thuộc tính module)."""
    tombstones.save(config_dir, tombstones.to_records(items, wall_now))


def _recency(scan: TempScan) -> tuple[bool, float, str]:
    """Khóa so “gần nhất” giữa các lượt RUNNING cùng máy gửi.

    Hoạt động cuối lớn hơn là gần hơn (None là cũ nhất); bằng nhau thì `transfer_id` lớn hơn.
    """
    last = scan.last_activity
    return (last is not None, 0.0 if last is None else last, scan.transfer_id)


def _positive_seconds(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} phải là số giây")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} phải là số hữu hạn > 0")
    return float(value)


def _error_label(e: BaseException) -> str:
    """Loại lỗi cho log, kèm `errno` nếu có; không bao giờ `str(e)` (có thể mang đường dẫn, mvp N9)."""
    number = getattr(e, "errno", None)
    return type(e).__name__ if number is None else f"{type(e).__name__} errno={number}"


_DISK_OPS: dict[type, DiskOp] = {
    CreateTemp: DiskOp.CREATE_TEMP,
    OpenPart: DiskOp.OPEN_PART,
    WriteBlock: DiskOp.WRITE,
    SyncPart: DiskOp.SYNC,
    ClearBlocks: DiskOp.SYNC,  # lỗi ghi `.state` như lỗi ghi `.state` khác (`ClearBlocks` docstring)
    Reread: DiskOp.REREAD,
    Finalize: DiskOp.FINALIZE,
}

_LaneAction = CreateTemp | OpenPart | WriteBlock | SyncPart | ClearBlocks | Reread | Finalize


@dataclass(eq=False)
class _DiskLane:
    """Hàng FIFO đĩa của một lượt nhận (hợp đồng `core/transfer.py` mục 5)."""

    device_id: str
    transfer_id: str
    # Thư mục nhận chụp đồng bộ lúc dựng hàng; mọi việc đĩa của hàng dùng nó (không đọc lại
    # `TransferManager._receive_dir`, có thể đã đổi). None: không có thư mục nhận (hàng lỗi ngay).
    rd: ReceiveDir | None = None
    ops: deque[tuple[_LaneAction, bytearray | None]] = field(default_factory=deque)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    stop: threading.Event = field(default_factory=threading.Event)  # dừng `Reread` đang chạy
    temp: TransferTemp | None = None
    parts: dict[int, PartFile] = field(default_factory=dict)
    pending_writes: int = 0  # `WriteBlock` đang giữ payload, chưa ghi xong (kể cả đang chạy)
    failed: bool = False
    closing: bool = False  # `RemoveTemp`, `SuspendTemp` hay lượt đã kết thúc: không báo engine nữa
    # `SuspendTemp`: thao tác đứng trước (trừ `Finalize` / `Reread` chưa chạy) vẫn chạy để `MARK`
    # bền, rồi chỉ đóng handle, không xóa.
    suspended: bool = False
    # Node đóng quá hạn hay bị hủy (`_close_lane(abandon=True)`): bỏ mọi thao tác chưa bắt đầu, dọn
    # chỉ đóng handle (`close_temp`), không bao giờ xóa.
    abandoned: bool = False
    keep_record: bool = False  # `RemoveTemp(keep_record=True)` (lượt DONE): giữ `transfer.json`
    jobs: set[DiskJob[Any]] = field(default_factory=set)  # việc đã giao mà chưa `done`
    create_job: DiskJob[TransferTemp] | None = None
    finalize_job: DiskJob[Path] | None = None  # `Finalize` đã giao cho executor, chưa xong
    waiters: set[asyncio.Event] = field(default_factory=set)  # bên đọc khung chờ chỗ trong hàng ghi


@dataclass(eq=False)
class _DirUse:
    """Ai đang dùng một `ReceiveDir` (`_retire_receive_dir` chỉ đóng nó khi không còn ai).

    `users`: task đã chụp thư mục này (hàng đĩa, dọn tạm, kiểm chỗ trống, `discard_temp`, đóng
    handle của khôi phục), đăng ký đồng bộ lúc chụp, trả khi task xong. `jobs`: việc đĩa đã giao
    với thư mục này mà có thể chưa `settled` (task chờ nó có thể đã thôi chờ vì quá hạn).
    """

    users: int = 0
    jobs: set[DiskJob[Any]] = field(default_factory=set)
    idle: asyncio.Event = field(default_factory=asyncio.Event)  # đặt khi `users` về 0


@dataclass(eq=False)
class _ProgressState:
    """Trạng thái báo tiến độ của một lượt (`_progress`)."""

    shown: int  # `shown_bytes` hiện tại: không bao giờ giảm
    raw: int  # `done_bytes + unsynced_bytes` ở nhịp trước (chưa kẹp, có thể giảm)
    active_at: float  # `loop.time()` lần cuối `raw` đổi (lần đầu thấy lượt là mốc)
    reported: tuple[int, int] | None = None  # (`shown`, `done_bytes`) lần phát gần nhất; None: chưa phát


# ---- Kết nối ---------------------------------------------------------------------------------


@dataclass(eq=False)
class _DataSlot:
    """Một kết nối dữ liệu engine đang theo dõi (`data_id`)."""

    data_id: int
    device_id: str
    conn: Connection
    task: asyncio.Task[None] | None = None  # `SendBlocks` / `ReceiveBlocks`
    closed: bool = False
    engine_closed: bool = False  # engine đã phát `CloseData` (đã quên kết nối): không báo lại
    done: asyncio.Event = field(default_factory=asyncio.Event)
    wake: asyncio.Event = field(default_factory=asyncio.Event)  # bên đọc khung đang chờ chỗ ghi


class _Outbox:
    """Hàng gửi FIFO có trần của một kết nối điều khiển, một task gửi.

    Trần chỉ xét khi đang có message gửi dở (máy kia chưa đọc): loạt message của một lời gọi engine
    xếp vào lúc hàng đang rảnh (ví dụ `offer` của mọi lượt khi đồng bộ lại, protocol §6.3) không bị
    tính là tràn, nên số lượt dở với một thiết bị lớn hơn trần không làm kết nối mới bị cắt lặp mãi.
    """

    def __init__(self, device_id: str, conn: Connection) -> None:
        self._device_id = device_id
        self._conn = conn
        self._queue: deque[TransferMessage] = deque()
        self._wake = asyncio.Event()
        self.idle = asyncio.Event()  # hàng rỗng và không có message đang gửi
        self.idle.set()
        self.closed = False
        self._sending = False  # task gửi đang có một message gửi dở
        self._task = asyncio.create_task(self._run(), name=f"{_TASK_NAME}.transfer-outbox {device_id[:8]}")

    @property
    def task(self) -> asyncio.Task[None]:
        return self._task

    def put(self, msg: TransferMessage) -> None:
        if self.closed:
            return
        if self._sending and len(self._queue) >= CONTROL_SEND_QUEUE_MAX:
            # Máy kia gửi liên tục mà không đọc: hàng phình mãi. Cắt kết nối → mất kết nối điều
            # khiển, nối lại và đồng bộ lại như thường (architecture §5).
            log.warning(
                "hàng gửi tới %s quá %d message, cắt kết nối điều khiển",
                self._device_id[:8],
                CONTROL_SEND_QUEUE_MAX,
            )
            self._conn.abort()
            self.close()
            return
        self._queue.append(msg)
        self.idle.clear()
        self._wake.set()

    def close(self) -> None:
        """Bỏ hàng, dừng task gửi (đổi hay mất kết nối điều khiển, hoặc node đóng)."""
        self.closed = True
        self._queue.clear()
        self.idle.set()
        self._task.cancel()

    async def _run(self) -> None:
        try:
            while True:
                while not self._queue:
                    self.idle.set()
                    self._wake.clear()
                    await self._wake.wait()
                msg = self._queue.popleft()
                self._sending = True
                try:
                    await self._conn.send(msg)
                except ConnectionLostError:
                    return
                except ValueError:
                    log.exception("không gửi được message %s tới %s", type(msg).__name__, self._device_id[:8])
                finally:
                    self._sending = False
        finally:
            self.closed = True
            self._queue.clear()
            self.idle.set()


@dataclass(eq=False)
class _ReadJobs:
    """Việc đĩa của một `SendBlocks` chưa chắc đã xong: mở file nguồn, khối đang chờ, khối đọc trước."""

    open: DiskJob[SourceReader] | None = None
    current: DiskJob[tuple[bytearray, bytes]] | None = None
    ahead: DiskJob[tuple[bytearray, bytes]] | None = None


@dataclass(eq=False)
class _Control:
    control_id: int
    conn: Connection
    outbox: _Outbox


# ---- TransferManager -------------------------------------------------------------------------


class TransferManager:
    """Lượt truyền file của một node. Chỉ `Node` tạo; xem docstring module."""

    def __init__(
        self,
        *,
        identity: Identity,
        hello: Hello,
        store: TrustStore,
        executor: DiskExecutor,
        receive_dir: ReceiveDir | None,
        config_dir: Path,
        auto_accept: bool,
        rate_limit: int | None,
        on_event: Callable[[TransferUpdate], None] | None,
        new_id: Callable[[], int],
        set_hold: Callable[[str, bool], None],
        ask_before_receive: Callable[[str], bool] | None = None,
    ) -> None:
        """Gọi trong event loop. `new_id` cấp `data_id`; `set_hold(device_id, held)` → `LinkTracker.hold`.

        `config_dir`: thư mục cấu hình của node, nơi đọc/ghi `tombstones.json`.
        `ask_before_receive(device_id)`: chính sách hỏi theo thiết bị, đọc đúng lúc có `offer` cần
        hỏi; chỉ khi trả đúng `False` thì tự nhận (raise → vẫn hỏi). None: luôn hỏi (trừ `auto_accept`).
        """
        self._identity = identity
        self._hello = hello
        self._store = store
        self._executor = executor
        self._receive_dir = receive_dir
        self._config_dir = Path(config_dir)
        self._on_event = on_event
        self._new_id = new_id
        self._set_hold = set_hold
        self._ask_before_receive = ask_before_receive
        self._loop = asyncio.get_running_loop()
        self._engine = TransferEngine(identity.device_id, receiving=receive_dir is not None)
        self._paused = False  # `pause_receiving`: chỉ trong phiên, không lưu
        self._retention: float | None = None  # `set_temp_retention`; None: `storage.TEMP_RETENTION`
        self._dir_uses: dict[ReceiveDir, _DirUse] = {}  # thư mục nhận → ai đang dùng (`_DirUse`)
        self._auto_accept = False
        self.auto_accept = auto_accept
        self._rate_limit: int | None = None
        self._bucket: TokenBucket | None = None
        self.rate_limit = rate_limit
        self._send_slots = asyncio.Semaphore(MAX_LIMITED_SENDS)

        self._dispatching = False
        self._deferred: deque[_Deferred] = deque()
        self._controls: dict[str, _Control] = {}
        self._data: dict[int, _DataSlot] = {}
        self._lanes: dict[tuple[str, str], _DiskLane] = {}
        self._live_lanes: set[_DiskLane] = set()  # hàng đĩa có task chưa xong (kể cả đang dọn)
        self._sources: dict[tuple[str, str], list[SourceFile]] = {}
        self._payload_sent: dict[tuple[str, str], int] = {}  # lượt gửi → byte payload đã giao
        self._final_paths: dict[tuple[str, str, int], Path] = {}
        self._payloads: dict[tuple[str, str, int, int], bytearray] = {}
        self._unpaired: set[TransferKey] = set()
        self._held: set[str] = set()
        self._hold_dirty = False
        self._tasks: set[asyncio.Task[Any]] = set()  # mạng, kiểm chỗ trống / nguồn: hủy khi đóng
        self._disk_tasks: set[asyncio.Task[Any]] = set()  # hàng đĩa, dọn file nguồn: chờ có hạn khi đóng
        self._timer_wake = asyncio.Event()
        self._timer_deadline: float | None = None
        self._timer_task: asyncio.Task[None] | None = None
        self._progress_wake = asyncio.Event()
        self._progress_task: asyncio.Task[None] | None = None
        self._samples: dict[TransferKey, deque[tuple[float, int]]] = {}
        self._progress_states: dict[TransferKey, _ProgressState] = {}
        self._closing = False  # begin_close() đã chạy: lời gọi công khai không làm gì
        self._closed = False  # close() xong: không phát sự kiện nữa
        # Khôi phục (`restore`): đã gọi chưa; `stop` của các lần mở lại (abort_now đặt).
        self._restore_called = False
        self._restore_stops: set[threading.Event] = set()
        # Ghi `tombstones.json` (mục “Bia mộ” ở docstring module).
        self._tomb_dirty = False  # bảng bia mộ đổi từ ảnh chụp cuối
        self._tomb_scheduled = False  # đã hẹn `_snapshot_tombstones`
        self._tomb_handle: asyncio.Handle | None = None  # `call_soon` / `call_later` đang hẹn
        self._tomb_task: asyncio.Task[None] | None = None  # lần ghi đang chạy (tới khi việc `settled`)
        self._tomb_job: DiskJob[None] | None = None  # việc đĩa của lần ghi gần nhất
        self._tomb_last_write: float | None = None  # `loop.time()` lúc lần ghi trước xong
        self._tomb_stopped = False  # đang xả lúc đóng hay đã hủy: không hẹn ghi nữa
        self._cleanup_job: DiskJob[int] | None = None  # lần dọn tạm gần nhất
        self._discarding: set[str] = set()  # `transfer_id` có `_discard_temp` chưa xong
        self._history = HistoryStore(executor=executor, config_dir=self._config_dir)
        # Đuôi đĩa (`_shutdown_disk`): executor đã dừng; task đóng thư mục nhận khi thread đĩa xong.
        self._disk_shut = False
        self._disk_tail: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Bật bộ hẹn giờ của engine và task tiến độ."""
        if self._timer_task is None:
            self._timer_task = asyncio.create_task(self._timer(), name=f"{_TASK_NAME}.transfer-timer")
            self._progress_task = asyncio.create_task(
                self._progress(), name=f"{_TASK_NAME}.transfer-progress"
            )

    # ---- API công khai ---------------------------------------------------------------------

    @property
    def receiving(self) -> bool:
        """Máy này có nhận `offer` mới không: có thư mục nhận, không tạm dừng nhận và node chưa đóng.

        Khi không nhận, `offer` mới nhận `reject{not_receiving}`; lượt đã có (kể cả `offer` gửi lại
        khi nối lại, lượt xếp hàng hay chờ hỏi) vẫn đi tiếp.
        """
        return self._engine.receiving

    @property
    def receiving_paused(self) -> bool:
        """Người dùng đang tạm dừng nhận (`pause_receiving`)."""
        return self._paused

    def pause_receiving(self, paused: bool) -> None:
        """Tạm dừng (True) hay nhận lại (False) `offer` mới; chỉ trong phiên này, không lưu.

        Chỉ đổi `engine.receiving` (không gọi engine), nên gọi được cả trong lúc đang thực hiện hành
        động của engine. Không phải bool → TypeError.
        """
        if type(paused) is not bool:
            raise TypeError("paused phải là bool")
        self._paused = paused
        self._apply_receiving()

    def _apply_receiving(self) -> None:
        self._engine.receiving = self._receive_dir is not None and not self._paused and not self._closing

    def busy_devices(self) -> frozenset[str]:
        """`device_id` của các thiết bị còn ít nhất một lượt chưa kết thúc, cả gửi lẫn nhận."""
        return frozenset(info.key.device_id for info in self._engine.transfers())

    def receive_dir_busy(self) -> bool:
        """Còn điều gì giữ thư mục nhận hiện tại, nên chưa đổi được (`replace_receive_dir`).

        True khi còn lượt nhận đã chấp nhận (`engine.has_accepted_receives`, kể cả lượt khôi phục),
        hàng đĩa còn sống, hay lượt thừa của khôi phục đang được xóa (`_discarding`). `offer` chưa
        nhận (đang xếp hàng, kiểm chỗ trống hay hỏi người dùng) không làm bận: đổi thư mục thì
        chúng được kiểm lại trên thư mục mới (`replace_receive_dir`).
        """
        return self._engine.has_accepted_receives() or bool(self._live_lanes) or bool(self._discarding)

    def replace_receive_dir(self, rd: ReceiveDir) -> None:
        """Dùng `rd` làm thư mục nhận từ giờ (đồng bộ); thư mục cũ đóng khi không còn ai dùng.

        Bận (`receive_dir_busy`) → `ReceiveDirBusy`; node đang đóng → RuntimeError; không đổi gì.
        Trước đó không có thư mục nhận thì từ giờ nhận `offer` (theo luật tạm dừng). Không khôi
        phục lượt dở có sẵn trong `rd` (chỉ `restore` lúc khởi động làm việc đó). `offer` đang kiểm
        chỗ trống hay đang hỏi người dùng được kiểm lại trên `rd` (`engine.recheck_space`, chỉ khi
        thư mục thật sự đổi và engine còn lượt nhận; đang thực hiện hành động thì lên đầu hàng
        hoãn: kết quả kiểm trên thư mục cũ bị bỏ, hộp hỏi không mở lại).
        """
        if not isinstance(rd, ReceiveDir):
            raise TypeError("rd phải là ReceiveDir")
        if self._closing:
            raise RuntimeError("node đang đóng")
        if self.receive_dir_busy():
            raise ReceiveDirBusy()
        old, self._receive_dir = self._receive_dir, rd
        self._apply_receiving()
        if old is not rd and any(
            info.key.direction is Direction.RECEIVE for info in self._engine.transfers()
        ):
            # `CheckSpace` mới chụp `rd` lúc giao việc. Không có lượt nhận thì không gọi engine
            # (`restore` phải là lời gọi đầu tiên của engine). Đang thực hiện hành động thì xếp
            # lên **đầu** hàng hoãn: một `decide(True)` hoãn từ trước phải gặp cờ kiểm lại, không
            # được chấp nhận lượt trên thư mục mới khi chưa kiểm chỗ trống ở đó.
            if self._dispatching:
                self._deferred.appendleft((self._engine.recheck_space, (), {}))
            else:
                self._call(self._engine.recheck_space)
        if old is not None and old is not rd:
            self._retire_receive_dir(old)

    def set_temp_retention(self, seconds: float | None) -> None:
        """Ngưỡng `TEMP_RETENTION` của `cleanup_temps` từ lần dọn sau; None: đọc `storage.TEMP_RETENTION`
        lúc dùng. Không phải số → TypeError; không hữu hạn hay ≤ 0 → ValueError."""
        if seconds is not None:
            seconds = _positive_seconds("seconds", seconds)
        self._retention = seconds

    async def cleanup_settled(self) -> None:
        """Chờ lần dọn tạm gần nhất (`cleanup_temps`) thật sự xong trong thread (nếu có)."""
        job = self._cleanup_job
        if job is not None:
            await job.settled()

    def set_hello(self, hello: Hello) -> None:
        """`hello` cho các kết nối dữ liệu mở từ giờ (máy này đổi tên). Sai → ValueError."""
        if not isinstance(hello, Hello) or hello.device_id != self._identity.device_id:
            raise ValueError("hello phải là Hello của danh tính này")
        self._hello = hello

    @property
    def receive_dir(self) -> Path | None:
        """Thư mục nhận (đường dẫn tuyệt đối); None nếu node không nhận file."""
        return None if self._receive_dir is None else self._receive_dir.root

    @property
    def auto_accept(self) -> bool:
        """Tự nhận mọi `offer` (`receive --yes`); đổi lúc chạy áp cho `offer` hỏi sau đó."""
        return self._auto_accept

    @auto_accept.setter
    def auto_accept(self, value: bool) -> None:
        if type(value) is not bool:
            raise ValueError("auto_accept phải là bool")
        self._auto_accept = value

    @property
    def rate_limit(self) -> int | None:
        """Giới hạn tốc độ gửi chung (byte/giây); None: không giới hạn. Sai → ValueError."""
        return self._rate_limit

    @rate_limit.setter
    def rate_limit(self, value: int | None) -> None:
        if value is not None and (type(value) is not int or value < MIN_RATE_LIMIT):
            raise ValueError(f"rate_limit phải là None hoặc số nguyên ≥ {MIN_RATE_LIMIT} (byte/giây)")
        self._rate_limit = value
        self._bucket = None if value is None else TokenBucket(value, ratelimit.CHUNK_SIZE)

    async def send(self, device_id: str, paths: Sequence[str | os.PathLike[str]]) -> TransferKey:
        """Gửi các file `paths` tới thiết bị tin cậy `device_id`; trả khóa của lượt.

        Ném lỗi trước khi gửi gì: node chưa chạy hay đang đóng → RuntimeError; không tin cậy →
        KeyError; `device_id` sai hay là máy này, 0 hoặc quá `MAX_OFFER_FILES` file, một file chọn
        hai lần → ValueError; `paths` không phải dãy đường dẫn → TypeError; file không gửi được →
        `SourceError`. Sự kiện của lượt có thể tới trước khi hàm trả về.
        """
        self._check_send_target(device_id)
        job = self._executor.submit(sources.prepare_sources, paths)
        try:
            files = await _job_result(job, None)
        except _JobDropped:
            raise RuntimeError("node đang đóng") from None
        except asyncio.CancelledError:
            job.cancel()
            raise
        # Kiểm lại sau await, cùng khối đồng bộ với `engine.send` (node có thể đang đóng, máy kia
        # có thể vừa bị hủy ghép đôi).
        self._check_send_target(device_id)
        if self._dispatching:
            raise RuntimeError("send() không được gọi trong lúc đang thực hiện hành động của engine")
        entries = [f.entry for f in files]
        while True:
            transfer_id = uuid4().hex
            try:
                actions = self._engine.send(device_id, transfer_id, entries, self._loop.time())
            except TransferIdInUse:
                continue
            break
        key = TransferKey(device_id, Direction.SEND, transfer_id)
        self._sources[(device_id, transfer_id)] = files
        self._dispatch_now(actions)
        self._drain_deferred()
        return key

    def decide(self, key: TransferKey, accept: bool) -> None:
        """Trả lời `OfferReceived`. Sai kiểu → TypeError; lượt không biết hay sai pha → bỏ qua."""
        if not isinstance(key, TransferKey):
            raise TypeError("key phải là TransferKey")
        if type(accept) is not bool:
            raise TypeError("accept phải là bool")
        if self._closing or key.direction is not Direction.RECEIVE or self._engine.info(key) is None:
            return
        self._call(self._engine.decide, key.device_id, key.transfer_id, accept)

    def cancel(self, key: TransferKey) -> None:
        """Hủy lượt `key` (ở trạng thái nào cũng được). Sai kiểu → TypeError; không biết → bỏ qua."""
        if not isinstance(key, TransferKey):
            raise TypeError("key phải là TransferKey")
        if self._closing or self._engine.info(key) is None:
            return
        self._call(self._engine.cancel, key)

    def cancel_all(self) -> None:
        """Hủy mọi lượt chưa kết thúc."""
        if not self._closing:
            self._cancel_every()

    def get(self, key: TransferKey) -> TransferInfo | None:
        """Bản chụp lượt `key`; None nếu không biết hoặc đã kết thúc."""
        return self._engine.info(key)

    def transfers(self) -> tuple[TransferInfo, ...]:
        """Mọi lượt chưa kết thúc, theo thứ tự tạo."""
        return self._engine.transfers()

    def history(self, device_id: str | None = None) -> tuple[HistoryEntry, ...]:
        """Lịch sử các lượt đã kết thúc (mvp F5), mới nhất trước; gọi được ở mọi lúc.

        `device_id` khác None: chỉ các lượt với máy đó (kể cả máy đã hủy ghép đôi); sai dạng →
        MessageError.
        """
        if device_id is not None:
            device_id = validate_device_id(device_id)
        return self._history.entries(device_id)

    def clear_history(self, device_id: str | None = None) -> None:
        """Xóa lịch sử (đồng bộ). None: toàn bộ, rỗng ngay trong bộ nhớ, ghi `history.json` rỗng
        (không xóa file). Một máy: bỏ mục của máy đó; file không đọc được lúc nạp thì chỉ xóa
        trong bộ nhớ, không ghi đè (`HistoryStore.clear`). `device_id` sai dạng → MessageError.

        Sau `close` chỉ xóa trong bộ nhớ (WARNING).
        """
        if device_id is not None:
            device_id = validate_device_id(device_id)
        self._history.clear(device_id)

    # ---- Cho Node ---------------------------------------------------------------------------

    async def restore(self) -> None:
        """Khôi phục lúc khởi động (mục “Khôi phục” ở docstring module); gọi đúng một lần, sau
        `start()`, trước khi mở cổng. Gọi lần hai → RuntimeError; ngoài ra chỉ ném CancelledError.

        Đọc `tombstones.json` (song song với `history.json`) và quét thư mục nhận (nếu có) qua
        `DiskExecutor`, mở lại song song
        lượt nhận dở gần nhất của mỗi máy gửi (hạn riêng mỗi lượt và hạn tổng; quá hạn hay lỗi
        thì bỏ lượt đó, để nguyên trên đĩa), rồi trong một khối đồng bộ: dựng hàng đĩa cho lượt
        mở được, gọi `engine.restore` (lời gọi engine đầu tiên, kể cả khi không có gì), phát
        `TransferResumed`, thực thi hành động. Lượt dở thừa của cùng máy gửi bị xóa
        (`discard_temp`) kèm bia mộ `expired` chưa gửi.
        """
        if self._restore_called:
            raise RuntimeError("restore() chỉ gọi được một lần")
        self._restore_called = True
        own = self._identity.device_id
        # Lịch sử nạp song song với bia mộ (cả hai chỉ ném CancelledError), xong trước
        # `_restore_apply` vì `engine.restore` có thể sinh `TransferEnded`.
        records, _ = await asyncio.gather(
            self._restore_load_tombstones(), self._history.load(DISK_OP_TIMEOUT)
        )
        rd = self._receive_dir
        scans: list[TempScan] = []
        if rd is not None and not self._closing:
            scans = await self._restore_scan(rd)
        # Xếp loại: mỗi máy gửi giữ lượt RUNNING gần nhất; lượt thừa thành bia mộ `expired`.
        # OTHER_NODE / ORPHAN / BROKEN không đụng (để “Dọn tạm”).
        wall = _wall_time()
        trusted = self._trusted_ids()
        running: dict[str, TempScan] = {}
        extra: list[TempScan] = []
        done: list[RestoredDone] = []
        for scan in scans:
            record = scan.record
            if record is None or record.sender == own or record.sender not in trusted:
                continue
            if scan.kind is TempKind.RUNNING:
                best = running.get(record.sender)
                if best is None or _recency(scan) > _recency(best):
                    if best is not None:
                        extra.append(best)
                    running[record.sender] = scan
                else:
                    extra.append(scan)
            elif scan.kind is TempKind.DONE and record.done_at is not None:
                age = max(0.0, wall - record.done_at.timestamp())
                done.append(RestoredDone(record.sender, record.offer, age))
        expired = str(CancelReason.EXPIRED)
        stones = [
            RestoredTombstone(s.record.sender, Direction.RECEIVE, s.transfer_id, expired, True, 0.0)
            for s in extra
            if s.record is not None
        ]
        handles: list[ResumeHandle] = []
        if rd is not None and running and not self._closing:
            handles = await self._restore_open(rd, list(running.values()))
        restored = self._restore_apply(rd, own, records, handles, stones, done)
        # Sau các lần mở lại (không làm chậm khởi động): xóa lượt thừa, chạy nền; chỉ khi engine đã
        # nhớ bia mộ `expired` của chúng (không thì máy gửi không bao giờ biết lý do).
        if rd is not None and restored and not self._closing:
            for scan in extra:
                self._discarding.add(scan.transfer_id)  # trước khi `Node` hẹn dọn tạm
                self._spawn(self._discard_temp(rd, scan.transfer_id), "transfer-discard", disk=True, rd=rd)

    async def cleanup_temps(self) -> int | None:
        """Dọn tạm một lần (`ReceiveDir.cleanup`, `Node` hẹn giờ); trả số thư mục lượt đã xóa.

        Bỏ qua (chụp đồng bộ ngay trước khi giao việc) `transfer_id` của mọi lượt nhận engine còn
        giữ, mọi hàng đĩa còn sống và mọi lượt thừa `restore` đang xóa (`_discarding`). Ngưỡng
        `retention`: `set_temp_retention`, chưa đặt thì `storage.TEMP_RETENTION` đọc lúc gọi. None khi:
        không có thư mục nhận, node đang đóng, lần dọn trước chưa xong, hay lần này lỗi / quá hạn
        `DISK_SYNC_TIMEOUT` (log, không ném).
        """
        rd = self._receive_dir
        if rd is None or self._closing:
            return None
        previous = self._cleanup_job
        if previous is not None and not previous.done:
            return None
        skip = {
            info.key.transfer_id
            for info in self._engine.transfers()
            if info.key.direction is Direction.RECEIVE
        }
        skip.update(lane.transfer_id for lane in self._live_lanes)
        skip.update(self._discarding)
        retention = storage.TEMP_RETENTION if self._retention is None else self._retention
        cleanup = functools.partial(
            rd.cleanup,
            _wall_time(),
            own_device_id=self._identity.device_id,
            skip=frozenset(skip),
            retention=retention,
        )
        try:
            job = self._executor.submit(cleanup)
        except RuntimeError:  # executor đã shutdown
            return None
        self._track_job(rd, job)
        self._cleanup_job = job
        try:
            return await _job_result(job, DISK_SYNC_TIMEOUT)
        except asyncio.CancelledError:
            if not job.cancel():
                # Đang chạy: để `close()` chờ nó (có hạn) trước khi đóng thư mục nhận.
                self._spawn(job.settled(), "transfer-cleanup-wait", disk=True)
            raise
        except Exception as e:  # DiskTimeout, `_JobDropped`, UnsafeReceiveDirError, OSError…
            log.warning("dọn tạm lỗi: %s", _error_label(e))
            return None

    def control_up(self, device_id: str, control_id: int, conn: Connection, *, client: bool) -> None:
        """Kết nối điều khiển hiện tại của thiết bị là `conn` (`LinkUp` hoặc `LinkSwitched`)."""
        old = self._controls.pop(device_id, None)
        if old is not None:
            old.outbox.close()
        outbox = _Outbox(device_id, conn)
        self._tasks.add(outbox.task)
        outbox.task.add_done_callback(self._tasks.discard)
        self._controls[device_id] = _Control(control_id, conn, outbox)
        self._call(self._engine.control_up, device_id, control_id, client)

    def control_lost(self, device_id: str, control_id: int) -> None:
        """Kết nối điều khiển `control_id` đã mất (`LinkDown`)."""
        ctl = self._controls.get(device_id)
        if ctl is not None and ctl.control_id == control_id:
            del self._controls[device_id]
            ctl.outbox.close()
        self._call(self._engine.control_lost, device_id, control_id)

    def on_message(self, device_id: str, control_id: int, msg: object) -> None:
        """Message tới trên kết nối điều khiển `control_id`; loại không phải truyền file bị bỏ qua."""
        if isinstance(msg, _TRANSFER_MESSAGE_TYPES):
            self._call(self._engine.message, device_id, control_id, msg)

    def forget_device(self, device_id: str) -> None:
        """Hủy ghép đôi (đồng bộ, trong `Node.unpair`): hủy mọi lượt của thiết bị, kết quả `UNPAIRED`."""
        for info in self._engine.transfers():
            if info.key.device_id == device_id:
                # Thêm trước lời gọi: `TransferEnded` được báo ngay trong lời gọi đó.
                self._unpaired.add(info.key)
                if not self._call(self._engine.cancel, info.key):
                    self._unpaired.discard(info.key)

    async def serve_data(self, conn: Connection) -> None:
        """Kết nối dữ liệu vào (đã qua kiểm tin cậy): báo engine trước `await` đầu, giữ tới khi xong."""
        opening = conn.opening
        if self._closing or conn.peer.cert is None or not isinstance(opening, DataOpen):
            conn.abort()
            return
        device_id = conn.peer.cert.device_id
        slot = _DataSlot(self._new_id(), device_id, conn)
        self._data[slot.data_id] = slot
        if not self._call(self._engine.incoming_data, device_id, slot.data_id, opening):
            self._finish_slot(slot, abort=True)
            return
        try:
            await slot.done.wait()
        finally:
            if not slot.closed and slot.task is None:
                # Bị hủy (cổng đóng) khi engine còn giữ kết nối chờ `resume`: báo engine quên nó.
                self._finish_slot(slot, abort=True)
                if not slot.engine_closed:
                    self._call(self._engine.data_closed, device_id, slot.data_id, False)

    def begin_close(self) -> None:
        """Bước đầu của `Node.close` (đồng bộ): tạm dừng lượt đang nhận, hủy các lượt còn lại.

        `engine.suspend_receiving` trước: mỗi lượt nhận đang chạy cắt kết nối dữ liệu, đẩy lô khối
        đã ghi (`SyncPart`) rồi `SuspendTemp` (thư mục tạm giữ nguyên cho lần `restore` sau, không
        gửi `cancel`), và kết thúc với `TransferFinished(SUSPENDED)` ngay trong lời gọi này. Sau đó
        ngừng nhận `offer`, từ chối `send` mới, hủy lượt gửi (`cancel{user}`) và `offer` đang chờ
        hỏi hay xếp hàng (`reject{user}`).
        """
        if self._closing:
            return
        self._closing = True
        self._call(self._engine.suspend_receiving)
        self._apply_receiving()  # `_closing`: không nhận nữa
        self._cancel_every()

    def control_idle(self, device_id: str, control_id: int) -> asyncio.Event | None:
        """Sự kiện “hàng gửi điều khiển trống” của kết nối `control_id` với thiết bị (đặt khi hàng
        rỗng và không có message đang gửi, hay hàng đã đóng); None nếu đó không phải kết nối điều
        khiển hiện tại. `ClipboardSync` chờ nó trước mỗi mảnh clip để nhường message truyền file."""
        ctl = self._controls.get(device_id)
        if ctl is None or ctl.control_id != control_id:
            return None
        return ctl.outbox.idle

    async def flush_control(self, timeout: float) -> None:
        """Chờ tối đa `timeout` giây cho mọi hàng gửi điều khiển trống (đẩy hết các `cancel`)."""
        outboxes = [c.outbox for c in self._controls.values() if not c.outbox.closed]
        if not outboxes:
            return
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(timeout):
                for outbox in outboxes:
                    await outbox.idle.wait()

    async def close(self) -> None:
        """Hủy task mạng, chờ các hàng đĩa xong tối đa `CLOSE_DISK_WAIT`, xả bia mộ, đóng thư mục nhận.

        Thứ tự: `begin_close()` (nếu chưa); hủy task mạng; chờ các hàng đĩa dọn xong (`RemoveTemp`)
        hay chạy nốt thao tác của lượt tạm dừng (`SuspendTemp`) tối đa `CLOSE_DISK_WAIT`; xả
        `tombstones.json` (`_flush_tombstones`) và `history.json` song song, cùng hạn
        `TOMBSTONE_FLUSH_TIMEOUT`; rồi
        `_shutdown_disk()`: `DiskExecutor.shutdown()` và đóng thư mục nhận (ngay, hay ở đuôi đĩa).

        Hết `CLOSE_DISK_WAIT` mà hàng đĩa chưa xong (WARNING): **không hủy** task của chúng (hủy
        giữa `await` một việc đĩa thì không bao giờ tới bước dọn, handle rò tới khi tiến trình
        thoát); mọi hàng bỏ thao tác chưa bắt đầu (`_close_lane(abandon=True)`) **trước** khi xả bia
        mộ và lịch sử, để không việc mới nào chiếm thread của lần ghi `tombstones.json` /
        `history.json`. Việc đang chạy trong
        thread xong thì hàng chỉ đóng handle (`close_temp`, không xóa) rồi đuôi đĩa đóng thư mục
        nhận; `close()` không chờ phần này (`close_time_limit()` không đổi). Đuôi chỉ có tác dụng
        khi event loop còn chạy: CLI thoát ngay sau `close()`, thread đĩa (daemon) chết theo; loop
        kết thúc trước đuôi thì đuôi bị hủy và handle rò tới hết tiến trình.
        Gọi lại được. Bị hủy giữa chừng → bên gọi dùng `abort_now()`.
        """
        if self._closed:
            return
        self.begin_close()
        for ctl in self._controls.values():
            ctl.outbox.close()
        tasks = [t for t in (self._timer_task, self._progress_task, *self._tasks) if t is not None]
        while tasks:
            for task in tasks:
                task.cancel()
            await asyncio.wait(tasks)
            # Task bị hủy có thể còn báo engine lúc kết thúc và sinh task mới: hủy nốt.
            tasks = [t for t in self._tasks if not t.done()]
        for lane in list(self._lanes.values()):
            self._close_lane(lane)
        disk = set(self._disk_tasks)
        if disk:
            _, pending = await asyncio.wait(disk, timeout=CLOSE_DISK_WAIT)
            if pending:
                log.warning("còn %d việc dọn đĩa chưa xong khi đóng", len(pending))
                self._abandon_lanes()  # trước khi xả bia mộ và lịch sử: không việc mới nào chiếm thread
        await asyncio.gather(self._flush_tombstones(), self._history.flush(TOMBSTONE_FLUSH_TIMEOUT))
        self._shutdown_disk()
        self._closed = True

    def abort_now(self) -> None:
        """`Node.close` (hay `Node.start`) bị hủy: hủy task mạng, hẹn giờ, tiến độ và lần ghi bia mộ,
        không chờ đĩa, không xả bia mộ và lịch sử; dừng mọi lần mở lại của `restore`.

        **Không hủy task đĩa** (`_disk_tasks`: hàng đĩa, đóng file nguồn, đóng handle mở lại tới
        muộn): mọi hàng bỏ thao tác chưa bắt đầu (`_close_lane(abandon=True)`), rồi
        `_shutdown_disk()` bỏ việc còn xếp hàng ở executor, nên các task này chỉ còn chờ việc đang
        chạy trong thread rồi chạy bước dọn (đóng handle trên loop vì `submit` đã bị từ chối); thư
        mục nhận đóng ngay hay ở đuôi đĩa. Đồng bộ.
        """
        self._closing = True
        self._closed = True
        self._stop_tombstones()
        self._history.stop()
        for stop in self._restore_stops:
            stop.set()
        for ctl in self._controls.values():
            ctl.outbox.close()
        tasks = (self._timer_task, self._progress_task, self._tomb_task, *self._tasks)
        for task in tasks:
            if task is not None:
                task.cancel()
        for slot in list(self._data.values()):
            self._finish_slot(slot, abort=True)
        self._abandon_lanes()
        self._shutdown_disk()

    def _abandon_lanes(self) -> None:
        """Mọi hàng đĩa còn sống (kể cả đang dọn hay tạm dừng): `_close_lane(abandon=True)`."""
        for lane in {*self._lanes.values(), *self._live_lanes}:
            self._close_lane(lane, abandon=True)

    def _live_disk_tasks(self) -> list[asyncio.Task[Any]]:
        return [t for t in self._disk_tasks if not t.done()]

    def _shutdown_disk(self) -> None:
        """`DiskExecutor.shutdown()` rồi đóng thư mục nhận: ngay, hay ở đuôi đĩa (gọi lại được).

        `shutdown()` trước: việc chưa chạy bị bỏ, không thread nào nhận việc mới. Không còn task
        đĩa sống và `busy == 0` → `ReceiveDir.close()` ngay. An toàn dù task đĩa sinh sau đó (ví dụ
        `_close_reader` trong `finally` của task gửi vừa hủy): chúng không dùng thư mục nhận, và
        `submit` của chúng bị từ chối. Còn task đĩa sống hay thread bận → một task đuôi duy nhất
        (`_disk_tail`, `_close_receive_dir_when_idle`) đóng thư mục nhận khi mọi việc dùng nó đã
        `settled()`. Không có hạn: đóng fd dưới tay một thread còn treo là không an toàn. Task đuôi
        và task đĩa từ đây được giữ ở `_detached_tasks` (`Node` có thể bỏ `TransferManager`).
        """
        self._executor.shutdown()
        self._disk_shut = True
        for task in self._live_disk_tasks():
            _keep_detached(task)
        rd = self._receive_dir
        if rd is None or rd.closed or self._disk_tail is not None:
            return
        busy = self._executor.busy
        if busy == 0 and not self._live_disk_tasks():
            rd.close()
            return
        if busy:
            log.warning("còn %d thao tác đĩa đang chạy: đóng thư mục nhận sau khi thread đĩa xong", busy)
        self._disk_tail = self._loop.create_task(
            self._close_receive_dir_when_idle(rd), name=f"{_TASK_NAME}.transfer-disk-tail"
        )
        _keep_detached(self._disk_tail)

    async def _close_receive_dir_when_idle(self, rd: ReceiveDir) -> None:
        """Đuôi đĩa: chờ mọi task đĩa xong (chụp lại `_disk_tasks` mỗi vòng: task mới có thể sinh
        trong lúc chờ) và mọi thread đĩa rảnh, rồi đóng thư mục nhận.

        Lần kiểm cuối và `rd.close()` nằm trong một khối đồng bộ (không `await` xen giữa).
        """
        try:
            while True:
                live = self._live_disk_tasks()
                if live:
                    await asyncio.wait(live)
                    continue
                if self._executor.busy == 0:
                    if not rd.closed:
                        rd.close()
                    return
                await self._executor.wait_idle(_TAIL_IDLE_POLL)
        except Exception:
            log.exception("đóng thư mục nhận sau khi thread đĩa xong lỗi")

    # ---- Gọi engine -------------------------------------------------------------------------

    def _call(self, method: Callable[..., list[TransferAction]], *args: Any, **kwargs: Any) -> bool:
        """Gọi engine với `now` đọc lúc gọi rồi thực hiện hành động; đang thực hiện thì hoãn.

        Trả False khi engine ném lỗi (đã ghi log); lời gọi bị hoãn trả True.
        """
        if self._dispatching:
            self._deferred.append((method, args, kwargs))
            return True
        ok = self._run(method, args, kwargs)
        self._drain_deferred()
        return ok

    def _drain_deferred(self) -> None:
        while self._deferred and not self._dispatching:
            method, args, kwargs = self._deferred.popleft()
            self._run(method, args, kwargs)

    def _run(
        self, method: Callable[..., list[TransferAction]], args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> bool:
        try:
            actions = method(*args, self._loop.time(), **kwargs)
        except Exception:
            log.exception("TransferEngine.%s ném lỗi", getattr(method, "__name__", "?"))
            return False
        self._dispatch_now(actions)
        return True

    def _dispatch_now(self, actions: list[TransferAction]) -> None:
        """Thực hiện danh sách hành động đồng bộ, rồi cập nhật `hold` và bộ hẹn giờ."""
        self._dispatching = True
        try:
            for action in actions:
                try:
                    self._execute(action)
                except Exception:
                    log.exception("thực hiện %s lỗi", type(action).__name__)
        finally:
            self._dispatching = False
        self._update_holds()
        self._wake_timer()

    def _execute(self, action: TransferAction) -> None:
        if isinstance(action, SendMessage):
            ctl = self._controls.get(action.device_id)
            if ctl is not None and ctl.control_id == action.control_id:
                ctl.outbox.put(action.message)
        elif isinstance(action, WriteBlock):
            self._enqueue_write(action)
        elif isinstance(action, SyncPart | ClearBlocks | OpenPart | Reread | Finalize):
            self._enqueue_disk(action)
        elif isinstance(action, Report):
            self._report(action.event)
        elif isinstance(action, CloseData):
            slot = self._data.get(action.data_id)
            if slot is not None:
                slot.engine_closed = True
                self._finish_slot(slot, abort=True)
        elif isinstance(action, SendBlocks | ReceiveBlocks):
            self._start_data_task(action)
        elif isinstance(action, OpenData):
            self._open_data(action)
        elif isinstance(action, CreateTemp):
            self._create_lane(action)  # `transfer.json` ghi từ `action.offer` trong `_lane_op`
        elif isinstance(action, RemoveTemp):
            lane = self._lanes.get((action.device_id, action.transfer_id))
            if lane is not None:
                lane.keep_record = action.keep_record  # đặt trước `_close_lane` (lượt DONE giữ bản ghi)
                self._close_lane(lane)
        elif isinstance(action, SuspendTemp):
            lane = self._lanes.get((action.device_id, action.transfer_id))
            if lane is not None:
                lane.suspended = True  # đặt trước `_close_lane`: thao tác ghi đứng trước vẫn chạy
                self._close_lane(lane)
        elif isinstance(action, TombstonesChanged):
            # Không chụp ở đây (đang thực hiện danh sách hành động): hẹn `_snapshot_tombstones`.
            self._tomb_dirty = True
            self._schedule_tombstone_snapshot()
        elif isinstance(action, CheckSpace):
            rd = self._receive_dir  # chụp lúc giao việc
            self._spawn(self._check_space(action, rd), f"transfer-check {action.transfer_id[:8]}", rd=rd)
        elif isinstance(action, CheckSource):
            self._spawn(self._check_source(action), f"transfer-check {action.transfer_id[:8]}")
        elif isinstance(action, AskUser):
            self._ask_user(action)

    def _cancel_every(self) -> None:
        for info in self._engine.transfers():
            self._call(self._engine.cancel, info.key)

    def _check_send_target(self, device_id: str) -> None:
        if self._closing:
            raise RuntimeError("node đang đóng")
        validate_device_id(device_id)
        if device_id == self._identity.device_id:
            raise ValueError("không gửi file cho chính máy này")
        if self._store.get(device_id) is None:
            raise KeyError(device_id)

    def _spawn(
        self, coro: Any, name: str, *, disk: bool = False, rd: ReceiveDir | None = None
    ) -> asyncio.Task[Any]:
        """Tạo task (mạng hay đĩa). `rd`: task dùng thư mục nhận này; đăng ký ngay (đồng bộ) là một
        người dùng của nó tới khi task xong (`_retire_receive_dir` chờ)."""
        task = asyncio.create_task(coro, name=f"{_TASK_NAME}.{name}")
        tasks = self._disk_tasks if disk else self._tasks
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        if rd is not None:
            use = self._dir_use(rd)
            use.users += 1
            use.idle.clear()
            task.add_done_callback(functools.partial(self._release_dir, rd))
        if disk and self._disk_shut:
            _keep_detached(task)  # sau `_shutdown_disk`: `Node` có thể đã bỏ `TransferManager`
        return task

    # ---- Ai đang dùng thư mục nhận (đổi thư mục nhận lúc chạy) ------------------------------

    def _dir_use(self, rd: ReceiveDir) -> _DirUse:
        use = self._dir_uses.get(rd)
        if use is None:
            use = self._dir_uses[rd] = _DirUse()
        return use

    def _release_dir(self, rd: ReceiveDir, _task: object = None) -> None:
        """Một task dùng `rd` vừa xong (callback của task)."""
        use = self._dir_uses.get(rd)
        if use is None:
            return
        use.users = max(0, use.users - 1)
        if use.users == 0:
            use.idle.set()

    def _track_job(self, rd: ReceiveDir, job: DiskJob[Any]) -> None:
        """Việc đĩa `job` vừa giao với `rd` (đồng bộ, cùng khối với `submit`)."""
        use = self._dir_use(rd)
        use.jobs = {j for j in use.jobs if not j.done}
        use.jobs.add(job)

    def _retire_receive_dir(self, rd: ReceiveDir) -> None:
        """Thư mục nhận `rd` thôi dùng: task đĩa đóng nó khi không còn ai dùng (`_close_retired`)."""
        self._spawn(self._close_retired(rd), "transfer-retire-dir", disk=True)

    async def _close_retired(self, rd: ReceiveDir) -> None:
        """Chờ mọi việc đĩa đã giao với `rd` `settled()` và mọi task đã chụp `rd` xong, rồi đóng `rd`.

        Không có hạn: đóng fd khi một thread đĩa còn dùng nó là không an toàn. Lần kiểm cuối và
        `rd.close()` nằm trong một khối đồng bộ. Là task đĩa: `close()` chờ có hạn, rồi nó chạy nền
        (`_shutdown_disk` giữ nó), như đuôi đĩa.
        """
        try:
            while True:
                use = self._dir_uses.get(rd)
                if use is None:
                    break
                pending = [job for job in use.jobs if not job.done]
                if pending:
                    for job in pending:
                        await job.settled()
                    continue
                if use.users:
                    await use.idle.wait()
                    continue
                break
            self._dir_uses.pop(rd, None)
            if not rd.closed:
                rd.close()
        except Exception:
            log.exception("đóng thư mục nhận cũ lỗi")

    def _update_holds(self) -> None:
        """Thiết bị còn lượt chưa kết thúc ↔ `hold` ở `core.links` (chỉ tính lại khi tập lượt đổi)."""
        if not self._hold_dirty:
            return
        self._hold_dirty = False
        active = {info.key.device_id for info in self._engine.transfers()}
        changes = [(d, True) for d in sorted(active - self._held)]
        changes += [(d, False) for d in sorted(self._held - active)]
        for device_id, held in changes:
            if held:
                self._held.add(device_id)
            else:
                self._held.discard(device_id)
            try:
                self._set_hold(device_id, held)
            except Exception:
                log.exception("không đổi được hold của %s", device_id[:8])

    def _wake_timer(self) -> None:
        wake = self._engine.next_wakeup()
        if wake is not None and (self._timer_deadline is None or wake < self._timer_deadline):
            self._timer_wake.set()

    async def _timer(self) -> None:
        """Gọi `engine.tick` lúc `next_wakeup()`."""
        while True:
            wake = self._engine.next_wakeup()
            self._timer_deadline = wake
            if wake is None:
                await self._timer_wake.wait()
            else:
                delay = wake - self._loop.time()
                if delay > 0:
                    with contextlib.suppress(TimeoutError):
                        async with asyncio.timeout(delay):
                            await self._timer_wake.wait()
            self._timer_wake.clear()
            due = self._engine.next_wakeup()
            if due is not None and due <= self._loop.time():
                self._call(self._engine.tick)

    # ---- Sự kiện ----------------------------------------------------------------------------

    def _emit(self, update: TransferUpdate) -> None:
        if self._closed or self._on_event is None:
            return
        try:
            self._on_event(update)
        except Exception:
            log.exception("on_transfer_event raise")

    def _report(self, event: TransferEvent) -> None:
        if isinstance(event, StatusChanged):
            self._hold_dirty = True
            self._progress_wake.set()
            info = self._engine.info(event.key)
            if info is not None:
                self._emit(TransferStatusChanged(info))
        elif isinstance(event, FileVerified):
            key = event.key
            path = None
            if key.direction is Direction.RECEIVE:
                path = self._final_paths.get((key.device_id, key.transfer_id, event.file_index))
            self._emit(FileDone(key, event.file_index, event.name, path))
        elif isinstance(event, TransferEnded):
            self._hold_dirty = True
            result = _result_of(event, event.key in self._unpaired)
            sent = 0
            if event.key.direction is Direction.SEND:
                sent = self._payload_sent.pop((event.key.device_id, event.key.transfer_id), 0)
            if result is not TransferResult.SUSPENDED:
                # Trước `_forget_transfer` (xóa `_final_paths`) và trước `_emit`.
                self._record_history(event.info, result)
            self._forget_transfer(event.key)
            ended = TransferFinished(
                event.info, result, event.by_peer, event.reason, event.file_index, event.reject, sent
            )
            self._emit(ended)
        elif isinstance(event, DataUnreachable):
            self._emit(event)

    def _record_history(self, info: TransferInfo, result: TransferResult) -> None:
        """Thêm mục lịch sử cho lượt vừa kết thúc (đồng bộ, không ném; mục “Lịch sử” ở docstring).

        `device_name`: tên trong `trusted.json` lúc này (None nếu đã hủy ghép đôi). `saved_path`:
        chỉ chiều nhận, đường dẫn file cuối có `file_index` nhỏ nhất còn trong `_final_paths`
        (lượt nối lại: file xong trước khi tạm dừng không có ở đó); đường dẫn không lưu được
        (không mã hóa được UTF-8, quá dài, có ký tự điều khiển) → None.
        """
        key = info.key
        try:
            device = self._store.get(key.device_id)
            device_name = None if device is None else device.name
            saved_path: str | None = None
            if key.direction is Direction.RECEIVE:
                pair = (key.device_id, key.transfer_id)
                indexes = [k[2] for k in self._final_paths if k[:2] == pair]
                if indexes:
                    text = str(self._final_paths[(*pair, min(indexes))])
                    with contextlib.suppress(UnicodeEncodeError):
                        text.encode("utf-8")
                        saved_path = text
            wall = _wall_time()
            try:
                entry = entry_from_info(
                    info, result=result, device_name=device_name, wall_now=wall, saved_path=saved_path
                )
            except HistoryError:
                if saved_path is None:
                    raise
                # Đường dẫn không lưu được (quá dài, ký tự lạ): vẫn giữ mục, không có đường dẫn.
                entry = entry_from_info(
                    info, result=result, device_name=device_name, wall_now=wall, saved_path=None
                )
        except Exception as e:
            log.warning("không ghi được lịch sử lượt %s: %s", key.transfer_id[:8], type(e).__name__)
            return
        self._history.record(entry)

    def _forget_transfer(self, key: TransferKey) -> None:
        """Lượt đã kết thúc: gỡ hàng đĩa, file nguồn, đường dẫn file cuối, dấu hủy ghép đôi."""
        pair = (key.device_id, key.transfer_id)
        self._unpaired.discard(key)
        self._samples.pop(key, None)
        self._progress_states.pop(key, None)
        if key.direction is Direction.SEND:
            self._sources.pop(pair, None)
            return
        lane = self._lanes.get(pair)
        if lane is not None:
            self._close_lane(lane)
        for path_key in [k for k in self._final_paths if k[:2] == pair]:
            del self._final_paths[path_key]

    def _ask_user(self, a: AskUser) -> None:
        key = TransferKey(a.device_id, Direction.RECEIVE, a.transfer_id)
        device = self._store.get(a.device_id)
        # Chính sách đọc đúng lúc này; chỉ `False` mới là "Luôn nhận" (lỗi → hỏi).
        auto = (self._auto_accept or not self._asks(a.device_id)) and not self._closing
        total = sum(entry.size for entry in a.offer.files)
        name = None if device is None else device.name
        self._emit(OfferReceived(key, name, a.offer.files, a.names, total, auto))
        if auto:
            self._loop.call_soon(self._auto_decide, a.device_id, a.transfer_id)

    def _asks(self, device_id: str) -> bool:
        """Có hỏi người dùng trước khi nhận từ `device_id` không (`ask_before_receive`)."""
        if self._auto_accept or self._ask_before_receive is None:
            return True
        try:
            return self._ask_before_receive(device_id) is not False
        except Exception:
            log.exception("đọc chính sách hỏi trước khi nhận của %s lỗi: vẫn hỏi", device_id[:8])
            return True

    def _auto_decide(self, device_id: str, transfer_id: str) -> None:
        if not self._closing:
            self._call(self._engine.decide, device_id, transfer_id, True)

    async def _progress(self) -> None:
        """Mỗi `PROGRESS_INTERVAL`: `TransferProgress` theo luật ở docstring của lớp đó."""
        while True:
            if not self._engine.transfers():
                self._progress_wake.clear()
                await self._progress_wake.wait()
            await asyncio.sleep(PROGRESS_INTERVAL)
            self._progress_tick(self._loop.time())

    def _progress_tick(self, now: float) -> None:
        """Một nhịp của `_progress` (tách riêng, đồng bộ, để test được luật phát)."""
        live: set[TransferKey] = set()
        for info in self._engine.transfers():
            key = info.key
            live.add(key)
            total = info.total_bytes
            # Byte hiển thị gồm cả khối đã giao ghi mà chưa `fsync` (bên nhận), để thanh không
            # nhảy bậc theo lô `SyncPart`; giữ không giảm (nối lại có thể bỏ khối chưa sync).
            raw = info.done_bytes + info.unsynced_bytes
            current = min(total, max(0, raw))
            state = self._progress_states.get(key)
            if state is None:
                state = self._progress_states[key] = _ProgressState(current, raw, now)
            else:
                if raw != state.raw:
                    # Có hoạt động kể cả khi `shown` không tăng (gửi lại khối sau nối lại, bỏ khối
                    # chưa sync): mốc của `idle_seconds`.
                    state.raw, state.active_at = raw, now
                if current > state.shown:
                    state.shown = current
            shown = state.shown
            samples = self._samples.setdefault(key, deque())
            samples.append((now, shown))
            while samples[0][0] < now - SPEED_WINDOW:
                samples.popleft()
            moving = info.status in (TransferStatus.TRANSFERRING, TransferStatus.RECONNECTING)
            # Lô cuối `synced` rồi sang VERIFYING: `shown` đứng nguyên nhưng `done_bytes` tăng tới
            # cuối file; vẫn phát để CLI thấy 100 %.
            if state.reported == (shown, info.done_bytes) and not moving:
                continue
            state.reported = (shown, info.done_bytes)
            first_t, first_shown = samples[0]
            span = now - first_t
            speed = max(0.0, (shown - first_shown) / span) if span > 0 else 0.0
            eta = (total - shown) / speed if speed > 0 else None
            idle = now - state.active_at
            self._emit(TransferProgress(info, speed, eta, shown, idle))
        for key in [k for k in self._samples if k not in live]:
            del self._samples[key]
        for key in [k for k in self._progress_states if k not in live]:
            del self._progress_states[key]

    # ---- Kết nối dữ liệu --------------------------------------------------------------------

    def _finish_slot(self, slot: _DataSlot, *, abort: bool) -> None:
        """Gỡ kết nối dữ liệu khỏi bảng, cắt nó (trừ khi đã đóng gọn), đánh thức bên chờ."""
        slot.closed = True
        if self._data.get(slot.data_id) is slot:
            del self._data[slot.data_id]
        if abort:
            slot.conn.abort()
        slot.wake.set()
        slot.done.set()

    def _open_data(self, a: OpenData) -> None:
        ctl = self._controls.get(a.device_id)
        device = self._store.get(a.device_id)
        if self._closing or ctl is None or ctl.control_id != a.control_id or device is None:
            # Engine không có hạn chờ cho `OpenData`: luôn báo kết quả (giao sau).
            self._call(self._engine.outgoing_data_failed, a.device_id, a.control_id, a.message)
            return
        peer = ctl.conn.peer
        self._spawn(
            self._open_data_task(a, peer.address, peer.port, device.cert_pem),
            f"transfer-open {a.message.transfer_id[:8]}",
        )

    async def _open_data_task(self, a: OpenData, address: str, port: int, cert_pem: str) -> None:
        device_id = a.device_id
        try:
            conn = await open_data(address, port, self._identity, self._hello, cert_pem, a.message)
        except (IdentityMismatch, VersionMismatch) as e:
            # Đúng địa chỉ:cổng của một kết nối điều khiển đã kiểm chứng chỉ mà danh tính hay phiên
            # bản khác: không phải tường lửa. Đóng kết nối điều khiển để lần nối lại báo đúng lỗi.
            log.warning(
                "kết nối dữ liệu tới %s: %s, đóng kết nối điều khiển", device_id[:8], type(e).__name__
            )
            ctl = self._controls.get(device_id)
            if ctl is not None and ctl.control_id == a.control_id:
                ctl.conn.abort()
            self._call(self._engine.outgoing_data_failed, device_id, a.control_id, a.message)
            return
        except (ValueError, TypeError):
            log.exception("lỗi khi mở kết nối dữ liệu tới %s", device_id[:8])
            self._call(self._engine.outgoing_data_failed, device_id, a.control_id, a.message)
            return
        except Exception as e:
            log.debug("không mở được kết nối dữ liệu tới %s: %s", device_id[:8], type(e).__name__)
            self._call(self._engine.outgoing_data_failed, device_id, a.control_id, a.message)
            return
        if self._closing:
            conn.abort()
            self._call(self._engine.outgoing_data_failed, device_id, a.control_id, a.message)
            return
        slot = _DataSlot(self._new_id(), device_id, conn)
        self._data[slot.data_id] = slot
        self._call(self._engine.outgoing_data, device_id, a.control_id, slot.data_id, a.message)
        if slot.task is None and not slot.closed:
            # Engine ném lỗi (đã ghi log) hoặc không giữ kết nối: không để nó treo.
            self._finish_slot(slot, abort=True)

    def _start_data_task(self, a: SendBlocks | ReceiveBlocks) -> None:
        slot = self._data.get(a.data_id)
        if slot is not None and slot.task is not None:
            log.error("kết nối dữ liệu %d đã có task", a.data_id)
            return
        if slot is None or slot.closed or self._closing:
            if slot is not None:
                self._finish_slot(slot, abort=True)
            self._call(self._engine.data_closed, a.device_id, a.data_id, False)
            return
        if isinstance(a, SendBlocks):
            slot.task = self._spawn(self._send_blocks(slot, a), f"transfer-send {a.transfer_id[:8]}")
        else:
            slot.task = self._spawn(self._receive_blocks(slot, a), f"transfer-recv {a.transfer_id[:8]}")

    async def _before_chunk(self, n: int) -> None:
        """Móc giới hạn tốc độ của `write_block` (công thức ở docstring `core/ratelimit.py`)."""
        bucket = self._bucket
        if bucket is None:
            return
        delay = bucket.delay(n, self._loop.time())
        if delay > 0:
            await asyncio.sleep(delay)
        bucket.take(n, self._loop.time())

    async def _count_chunk(self, pair: tuple[str, str], n: int) -> None:
        """Móc `before_chunk` của một lượt gửi: giới hạn tốc độ, rồi cộng `n` vào `payload_sent`.

        Đếm trước khi đoạn được ghi (cận trên, `TransferFinished`); lượt đã kết thúc thì không đếm.
        """
        await self._before_chunk(n)
        if pair in self._sources:
            self._payload_sent[pair] = self._payload_sent.get(pair, 0) + n

    async def _acquire_send_slot(self, slot: _DataSlot) -> bool:
        """Có giới hạn tốc độ: chờ một chỗ trong `MAX_LIMITED_SENDS` (dừng chờ khi kết nối bị đóng)."""
        if self._bucket is None:
            return False
        while not slot.closed:
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(0.5):
                    await self._send_slots.acquire()
                    return True
        return False

    async def _send_blocks(self, slot: _DataSlot, a: SendBlocks) -> None:
        """`SendBlocks` (hợp đồng mục 3). Kết thúc: cắt kết nối (trừ khi đã đóng gọn), báo engine."""
        device_id, data_id = a.device_id, a.data_id
        jobs = _ReadJobs()
        limited = False
        graceful = False
        result: tuple[str, bool] | None = None  # ("closed" | "source", cờ)
        try:
            limited = await self._acquire_send_slot(slot)
            if not slot.closed:
                graceful = await self._send_file(slot, a, jobs)
                if graceful:
                    result = ("closed", True)
        except ConnectionLostError:
            result = ("closed", False)
        except SourceChanged:
            result = ("source", True)
        except (OSError, DiskTimeout, _JobDropped) as e:
            label = _error_label(e)
            log.info("đọc file nguồn của lượt %s, file %d lỗi: %s", a.transfer_id[:8], a.file_index, label)
            result = ("source", False)
        except Exception:
            log.exception("lỗi khi gửi khối của lượt %s, file %d", a.transfer_id[:8], a.file_index)
            result = ("source", False)
        finally:
            if limited:
                self._send_slots.release()
            if jobs.open is not None:
                # File nguồn chỉ đóng sau khi mọi việc mở/đọc đã thật sự xong (`SourceReader` không
                # thread-safe; việc quá hạn vẫn chạy trong thread).
                pending = [j for j in (jobs.open, jobs.current, jobs.ahead) if j is not None]
                self._spawn(self._close_reader(jobs.open, pending), "transfer-source-close", disk=True)
            self._finish_slot(slot, abort=not graceful)
        if result is None or slot.engine_closed:
            return
        kind, flag = result
        if kind == "closed":
            self._call(self._engine.data_closed, device_id, data_id, flag)
        else:
            self._call(self._engine.source_failed, device_id, a.transfer_id, a.file_index, flag)

    async def _send_file(self, slot: _DataSlot, a: SendBlocks, jobs: _ReadJobs) -> bool:
        """Ghi khung cho mọi khối thiếu, đọc trước một khối trong lúc ghi khối hiện tại.

        True: đã ghi hết rồi đóng gọn; False: dừng vì engine đóng kết nối. Lỗi bay ra.
        """
        device_id, data_id = a.device_id, a.data_id
        files = self._sources.get((device_id, a.transfer_id))
        if files is None or not 0 <= a.file_index < len(files):
            raise RuntimeError("không có file nguồn của lượt")
        source = files[a.file_index]
        before_chunk = functools.partial(self._count_chunk, (device_id, a.transfer_id))
        jobs.open = self._executor.submit(sources.SourceReader.open, source.path, source.entry)
        reader = await _job_result(jobs.open, DISK_OP_TIMEOUT)
        missing = a.have.missing()
        index = next(missing, None)
        if index is not None:
            jobs.ahead = self._executor.submit(reader.read_block, index)
        while index is not None and jobs.ahead is not None:
            jobs.current, jobs.ahead = jobs.ahead, None
            payload, digest = await _job_result(jobs.current, DISK_OP_TIMEOUT)
            following = next(missing, None)
            if following is not None:
                jobs.ahead = self._executor.submit(reader.read_block, following)
            if slot.closed:
                return False
            if not self._call(self._engine.block_read, device_id, data_id, index, digest):
                raise RuntimeError("engine từ chối block_read")
            if slot.closed:  # kết quả có `CloseData` của kết nối này: không ghi khung
                return False
            await slot.conn.write_block(index, digest, payload, before_chunk=before_chunk)
            del payload
            index = following
        await slot.conn.close()  # hết khối: đóng gọn, bên nhận đọc hết phần đuôi
        return True

    async def _close_reader(self, open_job: DiskJob[SourceReader], jobs: list[DiskJob[Any]]) -> None:
        """Đóng file nguồn sau khi mọi việc đọc đã thật sự xong (kể cả việc mở/đọc đã quá hạn)."""
        for job in jobs:
            await job.settled()
        reader = await _late_result(open_job)
        if reader is None:
            return
        try:
            job = self._executor.submit(reader.close)
        except RuntimeError:  # executor đã shutdown; mọi việc đọc đã xong ở trên
            reader.close()
            return
        await job.settled()
        if not job.started:  # bị shutdown bỏ trước khi chạy
            reader.close()

    async def _wait_write_room(self, slot: _DataSlot, pair: tuple[str, str]) -> None:
        """Chờ hàng ghi của lượt có chỗ (< `WRITE_QUEUE_BLOCKS`); thức cả khi kết nối / hàng đĩa đóng."""
        while not slot.closed:
            lane = self._lanes.get(pair)
            if lane is None or lane.failed or lane.closing or lane.pending_writes < WRITE_QUEUE_BLOCKS:
                return
            slot.wake.clear()
            lane.waiters.add(slot.wake)
            try:
                await slot.wake.wait()
            finally:
                lane.waiters.discard(slot.wake)

    async def _receive_blocks(self, slot: _DataSlot, a: ReceiveBlocks) -> None:
        """`ReceiveBlocks` (hợp đồng mục 4): đọc khung, so hash ngoài loop, báo engine."""
        device_id, data_id = a.device_id, a.data_id
        pair = (device_id, a.transfer_id)
        conn = slot.conn
        result: str | None = None  # "closed" | "bad"
        try:
            while not slot.closed:
                await self._wait_write_room(slot, pair)
                if slot.closed:
                    break
                try:
                    frame = await conn.read_block(size=a.size)
                except BlockError:
                    result = "bad"
                    break
                if frame is None:
                    result = "closed"
                    break
                header, payload = frame
                digest = await asyncio.to_thread(_sha256, payload)
                if slot.closed:
                    break
                if digest != header.sha256:
                    result = "bad"
                    break
                key = (device_id, a.transfer_id, a.file_index, header.index)
                self._payloads[key] = payload
                try:
                    self._call(self._engine.block_received, device_id, data_id, header.index, digest)
                finally:
                    # Engine không phát `WriteBlock` cho khối trùng, sai thứ tự hay kết nối đã quên:
                    # payload chỉ còn sống trong thao tác `WriteBlock` của hàng đĩa.
                    self._payloads.pop(key, None)
                del frame, payload
        except ConnectionLostError:
            result = "closed"
        except Exception:
            log.exception("lỗi khi nhận khối của lượt %s, file %d", a.transfer_id[:8], a.file_index)
            result = "closed"
        finally:
            self._finish_slot(slot, abort=True)
        if result is None or slot.engine_closed:
            return
        if result == "bad":
            self._call(self._engine.block_bad, device_id, data_id)
        else:
            self._call(self._engine.data_closed, device_id, data_id, False)

    # ---- Kiểm chỗ trống / file nguồn ---------------------------------------------------------

    async def _check_space(self, a: CheckSpace, rd: ReceiveDir | None) -> None:
        free: int | None = None
        max_size: int | None = None
        if rd is not None and not self._closing:
            job = None
            try:
                job = self._executor.submit(rd.volume_info)
                self._track_job(rd, job)
                info = await _job_result(job, DISK_OP_TIMEOUT)
            except asyncio.CancelledError:
                if job is not None:
                    job.cancel()
                raise
            except Exception as e:  # gồm DiskTimeout, `_JobDropped`, RuntimeError sau shutdown
                log.info("không đọc được dung lượng thư mục nhận: %s", _error_label(e))
            else:
                free, max_size = info.free_bytes, info.max_file_size
        self._call(
            self._engine.space_checked, a.device_id, a.transfer_id, free, max_size, check_id=a.check_id
        )

    async def _check_source(self, a: CheckSource) -> None:
        files = self._sources.get((a.device_id, a.transfer_id))
        if files is None or not 0 <= a.file_index < len(files) or self._closing:
            self._call(self._engine.source_failed, a.device_id, a.transfer_id, a.file_index, False)
            return
        job = None
        try:
            job = self._executor.submit(sources.check_source, files[a.file_index].path, a.leaves)
            size, mtime, root = await _job_result(job, DISK_OP_TIMEOUT)
        except asyncio.CancelledError:
            if job is not None:
                job.cancel()
            raise
        except SourceChanged:
            self._call(self._engine.source_failed, a.device_id, a.transfer_id, a.file_index, True)
            return
        except Exception as e:
            label = _error_label(e)
            log.info("kiểm file nguồn của lượt %s, file %d lỗi: %s", a.transfer_id[:8], a.file_index, label)
            self._call(self._engine.source_failed, a.device_id, a.transfer_id, a.file_index, False)
            return
        self._call(self._engine.source_checked, a.device_id, a.transfer_id, a.file_index, size, mtime, root)

    # ---- Hàng đĩa ---------------------------------------------------------------------------

    def _create_lane(self, a: CreateTemp) -> None:
        pair = (a.device_id, a.transfer_id)
        if pair in self._lanes:
            log.error("lượt %s đã có hàng đĩa", a.transfer_id[:8])
            self._call(self._engine.storage_failed, a.device_id, a.transfer_id, DiskOp.CREATE_TEMP)
            return
        lane = _DiskLane(a.device_id, a.transfer_id, rd=self._receive_dir)
        self._lanes[pair] = lane
        self._live_lanes.add(lane)
        if lane.rd is None or self._closing:
            # Không tạo được: hàng đĩa ở trạng thái lỗi, các thao tác sau của lượt bị bỏ im lặng
            # tới khi lượt kết thúc (engine nhận `storage_failed` đúng một lần).
            self._fail_lane(lane, DiskOp.CREATE_TEMP)
        else:
            lane.ops.append((a, None))
        self._spawn(self._run_lane(lane), f"transfer-disk {a.transfer_id[:8]}", disk=True, rd=lane.rd)

    def _lane_for(self, action: _LaneAction) -> _DiskLane | None:
        lane = self._lanes.get((action.device_id, action.transfer_id))
        if lane is None:
            log.error("không có hàng đĩa cho %s của lượt %s", type(action).__name__, action.transfer_id[:8])
            op = _DISK_OPS[type(action)]
            self._call(self._engine.storage_failed, action.device_id, action.transfer_id, op)
        return lane

    def _enqueue_write(self, a: WriteBlock) -> None:
        payload = self._payloads.pop((a.device_id, a.transfer_id, a.file_index, a.index), None)
        lane = self._lane_for(a)
        if lane is None or lane.failed or lane.closing:
            return
        if payload is None:
            log.error("thiếu payload của khối %d, lượt %s", a.index, a.transfer_id[:8])
            self._fail_lane(lane, DiskOp.WRITE)
            return
        lane.ops.append((a, payload))
        lane.pending_writes += 1
        lane.wake.set()

    def _enqueue_disk(self, action: OpenPart | SyncPart | ClearBlocks | Reread | Finalize) -> None:
        lane = self._lane_for(action)
        if lane is None or lane.failed or lane.closing:
            return
        lane.ops.append((action, None))
        lane.wake.set()

    @staticmethod
    def _notify_lane(lane: _DiskLane) -> None:
        for waiter in list(lane.waiters):
            waiter.set()

    @staticmethod
    def _drop_ops(lane: _DiskLane) -> None:
        """Bỏ mọi thao tác chưa bắt đầu, trả lại chỗ trong hàng ghi."""
        dropped = sum(isinstance(action, WriteBlock) for action, _ in lane.ops)
        lane.ops.clear()
        lane.pending_writes -= dropped

    @staticmethod
    def _drop_suspended_ops(lane: _DiskLane) -> None:
        """Lane tạm dừng: bỏ `Finalize` và `Reread` chưa bắt đầu, giữ các thao tác làm `MARK` bền.

        Phòng thủ: `Finalize` thường đã được `submit` ngay khi tới lượt trong hàng, nên đường thực
        tế là `finalize_job.cancel()` ở `_close_lane`; lọc `lane.ops` chỉ bắt ca còn nằm trong hàng.
        """
        lane.ops = deque(item for item in lane.ops if not isinstance(item[0], Finalize | Reread))

    def _close_lane(self, lane: _DiskLane, *, abandon: bool = False) -> None:
        """`RemoveTemp`, `SuspendTemp` hay lượt đã kết thúc: dừng `Reread`, gỡ hàng, thôi báo engine.

        Thường thì bỏ mọi thao tác chưa chạy. Lane `suspended` thì chỉ bỏ `Finalize` và `Reread`
        chưa bắt đầu (`Finalize` đã giao executor mà thread chưa nhận bị hủy bằng
        `finalize_job.cancel()`, đường thường gặp vì `Finalize` được `submit` ngay khi tới lượt;
        lọc `lane.ops` chỉ là phòng thủ; `Reread` đã giao
        thì dừng trước khối đầu vì `stop` đã đặt); các thao tác khác đứng trước `SuspendTemp`
        (`WriteBlock`, `SyncPart`, `ClearBlocks`, cả `CreateTemp` / `OpenPart` chưa chạy) vẫn chạy
        để `MARK` của lô cuối bền. Bỏ `Finalize` để lượt báo `SUSPENDED` không xong ngầm trên đĩa:
        lần chạy sau khôi phục `.part` đủ bit, máy gửi nối lại và gửi lại `complete`, rồi mới
        `Reread` → `Finalize`. `Reread` đang chạy dừng ngay (đọc lại không đổi gì trên đĩa). Giới
        hạn đã biết: `Finalize` **đang chạy** (thread đã nhận việc) lúc tạm dừng thì chạy tới cùng
        (hợp đồng mục 5), nên trong cửa sổ đó (vài ms) lượt có thể đã xong trên đĩa dù báo
        `SUSPENDED`. Task của hàng chờ thao tác đang chạy xong rồi mới dọn (`_cleanup_lane`).

        `abandon` (node đóng quá hạn hay bị hủy; áp cả cho hàng đã đóng, đang dọn hay tạm dừng):
        bỏ mọi thao tác chưa bắt đầu, kể cả `Finalize` đã giao mà thread chưa nhận; khi dọn chỉ
        đóng handle (`close_temp`), không bao giờ `remove_temp`.
        """
        if self._lanes.get((lane.device_id, lane.transfer_id)) is lane:
            del self._lanes[(lane.device_id, lane.transfer_id)]
        if abandon:  # trước lần kiểm `closing`: hàng đã đóng cũng phải bỏ thao tác còn lại
            lane.abandoned = True
            lane.stop.set()
            self._drop_ops(lane)
            if lane.finalize_job is not None:
                lane.finalize_job.cancel()  # chỉ bỏ được khi thread chưa nhận việc
            self._notify_lane(lane)
            lane.wake.set()
        if lane.closing:
            return
        lane.closing = True
        lane.stop.set()
        if lane.suspended:
            self._drop_suspended_ops(lane)
            if lane.finalize_job is not None:
                lane.finalize_job.cancel()  # chỉ bỏ được khi thread chưa nhận việc
        else:
            self._drop_ops(lane)
        self._notify_lane(lane)
        lane.wake.set()

    def _fail_lane(self, lane: _DiskLane, op: DiskOp, detail: FailureDetail | None = None) -> None:
        """Thao tác lỗi: bỏ các thao tác còn lại của lượt (trừ dọn), báo `storage_failed`."""
        lane.failed = True
        self._drop_ops(lane)
        self._notify_lane(lane)
        if not lane.closing:
            self._call(self._engine.storage_failed, lane.device_id, lane.transfer_id, op, detail=detail)

    async def _run_lane(self, lane: _DiskLane) -> None:
        try:
            # Lane tạm dừng chạy nốt các thao tác đã xếp hàng rồi mới dọn (`_close_lane`).
            while not (lane.closing and (not lane.suspended or not lane.ops)):
                if not lane.ops:
                    lane.wake.clear()
                    await lane.wake.wait()
                    continue
                action, payload = lane.ops.popleft()
                try:
                    if not lane.failed:
                        await self._lane_op(lane, action, payload)
                finally:
                    del payload
                    if isinstance(action, WriteBlock):
                        lane.pending_writes -= 1
                        self._notify_lane(lane)
            await self._cleanup_lane(lane)
        finally:
            self._live_lanes.discard(lane)

    async def _lane_job[R](self, lane: _DiskLane, job: DiskJob[R], timeout: float) -> R:
        """Chờ một việc của hàng; việc chưa xong (quá hạn) ở lại `lane.jobs` để dọn chờ nó."""
        lane.jobs.add(job)
        try:
            return await _job_result(job, timeout)
        finally:
            if job.done:
                lane.jobs.discard(job)

    async def _lane_op(self, lane: _DiskLane, action: _LaneAction, payload: bytearray | None) -> None:
        device_id, transfer_id = lane.device_id, lane.transfer_id
        rd = lane.rd
        assert rd is not None

        def submit[R](fn: Callable[..., R], /, *args: object) -> DiskJob[R]:
            # Executor đã dừng (node đóng) khi hàng đang đóng: như việc bị bỏ trước khi chạy.
            # `RuntimeError` do chính hàm đĩa ném (qua `job.result`) không đi qua đây.
            try:
                return self._executor.submit(fn, *args)
            except RuntimeError:
                if lane.closing:
                    raise _JobDropped("executor đã dừng") from None
                raise

        try:
            if isinstance(action, CreateTemp):
                # `transfer.json` bền trước khi `create_temp` trả về: `temp_created` nghĩa là đã bền.
                record = TransferRecord(
                    receiver=self._identity.device_id,
                    sender=device_id,
                    offer=action.offer,
                    verified=0,
                    done_at=None,
                )
                lane.create_job = submit(rd.create_temp, transfer_id, record)
                lane.temp = await self._lane_job(lane, lane.create_job, DISK_OP_TIMEOUT)
                # Báo trước kết quả của mọi thao tác sau nó (hợp đồng mục 5): engine mới gửi `accept`.
                # Quá hạn thì `DiskTimeout` đã bay ra ở trên: xong muộn cũng không báo.
                if not lane.closing:
                    self._call(self._engine.temp_created, device_id, transfer_id)
            elif isinstance(action, OpenPart):
                if lane.temp is None:
                    raise ValueError("chưa có thư mục tạm")
                job = submit(lane.temp.create_part, action.file_index, action.size)
                lane.parts[action.file_index] = await self._lane_job(lane, job, DISK_OP_TIMEOUT)
            elif isinstance(action, WriteBlock):
                part = self._part(lane, action.file_index)
                await self._lane_job(lane, submit(part.write_at, action.index, payload), DISK_OP_TIMEOUT)
            elif isinstance(action, SyncPart):
                # `fsync` `.part` → nối `MARK` → `fsync` `.state`; `synced` chỉ sau khi `MARK` đã bền.
                part = self._part(lane, action.file_index)
                await self._lane_job(lane, submit(part.commit, action.blocks), DISK_SYNC_TIMEOUT)
                if not lane.closing:
                    self._call(self._engine.synced, device_id, transfer_id, action.file_index, action.token)
            elif isinstance(action, ClearBlocks):
                # Nối `CLEAR` / `CLEAR_ALL`, không `fsync` và không báo engine (architecture mục 4).
                part = self._part(lane, action.file_index)
                await self._lane_job(lane, submit(part.clear, action.indices), DISK_OP_TIMEOUT)
            elif isinstance(action, Reread):
                part = self._part(lane, action.file_index)
                n = len(action.leaves) // DIGEST_SIZE
                check = submit(_reread_compare, part, action.leaves, lane.stop)
                bad, root = await self._lane_job(lane, check, DISK_SYNC_TIMEOUT + n * REREAD_BLOCK_TIMEOUT)
                if not lane.closing:
                    self._call(self._engine.reread_done, device_id, transfer_id, action.file_index, bad, root)
            else:
                part = self._part(lane, action.file_index)
                finalize = functools.partial(rd.finalize, part, action.name, mtime_ms=action.mtime)
                # Còn xếp hàng ở executor (thread chưa nhận) thì `SuspendTemp` còn bỏ được (`_close_lane`).
                lane.finalize_job = submit(finalize)
                try:
                    path = await self._lane_job(lane, lane.finalize_job, DISK_SYNC_TIMEOUT)
                finally:
                    lane.finalize_job = None
                # `Finalize` đã bắt đầu thì chạy tới cùng (hợp đồng mục 5); lượt đã kết thúc giữa
                # chừng thì file vẫn mang tên thật, chỉ không báo nữa.
                if not lane.closing:
                    self._final_paths[(device_id, transfer_id, action.file_index)] = path
                    self._call(self._engine.finalized, device_id, transfer_id, action.file_index, path.name)
        except RereadStopped:
            return
        except _JobDropped:
            if lane.closing:
                return  # bị bỏ trước khi chạy (tạm dừng, hay node đóng): không phải lỗi của lượt
            log.warning("%s của lượt %s bị bỏ khi đóng", _DISK_OPS[type(action)].value, transfer_id[:8])
            self._fail_lane(lane, _DISK_OPS[type(action)])
        except TempExistsError:
            log.info("thư mục tạm của lượt %s đã có sẵn mà không dùng tiếp được", transfer_id[:8])
            self._fail_lane(lane, DiskOp.CREATE_TEMP, FailureDetail.TEMP_EXISTS)
        except ReceiveDirMissingError:
            log.warning("thư mục nhận đã mất và không tạo lại được (lượt %s)", transfer_id[:8])
            self._fail_lane(lane, DiskOp.CREATE_TEMP, FailureDetail.RECEIVE_DIR_MISSING)
        except Exception as e:
            op = _DISK_OPS[type(action)]
            index = getattr(action, "file_index", None)
            if isinstance(e, ValueError | TypeError):
                log.exception("lỗi khi %s của lượt %s, file %s", op.value, transfer_id[:8], index)
            else:
                label = _error_label(e)
                log.warning("%s của lượt %s, file %s lỗi: %s", op.value, transfer_id[:8], index, label)
            self._fail_lane(lane, op)

    @staticmethod
    def _part(lane: _DiskLane, file_index: int) -> PartFile:
        part = lane.parts.get(file_index)
        if part is None:
            raise ValueError(f"chưa có .part của file {file_index}")
        return part

    async def _cleanup_lane(self, lane: _DiskLane) -> None:
        """Chờ mọi việc của hàng thật sự xong, rồi dọn thư mục tạm của chính lượt này (nếu có).

        Lane `suspended` hay `abandoned` (kể cả khi một thao tác đã lỗi): chỉ đóng handle
        (`close_temp`), không xóa gì. Còn lại: `remove_temp` (giữ `transfer.json` khi `keep_record`).
        """
        lane.stop.set()
        self._drop_ops(lane)
        self._notify_lane(lane)
        for job in list(lane.jobs):
            await job.settled()
        lane.jobs.clear()
        temp = lane.temp
        if temp is None and lane.create_job is not None:
            # `create_temp` quá hạn rồi xong muộn: thư mục đó là của lượt này, xóa (hay đóng) nó.
            temp = await _late_result(lane.create_job)
        lane.temp = None
        lane.parts.clear()
        rd = lane.rd
        if temp is None or rd is None:
            return
        if lane.suspended or lane.abandoned:
            await self._close_temp(rd, temp)
            return
        # `remove_temp` đóng mọi `.part` của lượt (kể cả `.part` tạo muộn) rồi mới xóa.
        remove = functools.partial(rd.remove_temp, temp, keep_record=lane.keep_record)
        try:
            job = self._executor.submit(remove)
        except RuntimeError:
            return  # executor đã shutdown (node đóng quá hạn): để lại thư mục tạm
        await job.settled()
        if not job.started:
            return  # bị shutdown bỏ trước khi chạy (node đóng quá hạn): để lại thư mục tạm
        try:
            await job.result(None)
        except Exception as e:
            log.debug("xóa thư mục tạm của lượt %s lỗi: %s", lane.transfer_id[:8], _error_label(e))

    async def _close_temp(self, rd: ReceiveDir, temp: TransferTemp) -> None:
        """Chỉ đóng handle của `temp` (`close_temp`, không xóa gì) qua executor.

        `rd`: thư mục nhận chứa `temp`, bên gọi chụp đồng bộ lúc giao việc (thư mục nhận hiện tại
        có thể đã đổi). Điều kiện trước: mọi việc đĩa dùng `temp` đã `settled`. Executor đã
        shutdown (hay bỏ việc trước khi chạy) thì đóng ngay trên loop: chỉ là đóng fd, không thread
        nào còn dùng chúng.
        """
        job: DiskJob[None] | None = None
        with contextlib.suppress(RuntimeError):  # executor đã shutdown
            job = self._executor.submit(rd.close_temp, temp)
        if job is not None:
            await job.settled()
            if job.started:
                await _late_result(job)
                return
        try:
            rd.close_temp(temp)
        except ValueError as e:
            log.debug("đóng thư mục tạm của lượt %s lỗi: %s", temp.transfer_id[:8], _error_label(e))

    # ---- Khôi phục ---------------------------------------------------------------------------

    def _trusted_ids(self) -> set[str]:
        return {device.device_id for device in self._store.devices()}

    async def _restore_load_tombstones(self) -> list[TombstoneRecord]:
        """Bước 1 của `restore`: `tombstones.load` qua executor; hạn `DISK_OP_TIMEOUT` bao cả lúc
        chờ bắt đầu. Quá hạn hay lỗi → rỗng, WARNING."""
        try:
            job = self._executor.submit(tombstones.load, self._config_dir)
        except RuntimeError:  # executor đã shutdown
            return []
        try:
            async with asyncio.timeout(DISK_OP_TIMEOUT):
                return await _job_result(job, None)
        except asyncio.CancelledError:
            job.cancel()
            raise
        except Exception as e:  # gồm TimeoutError của `asyncio.timeout`, `_JobDropped`
            job.cancel()
            log.warning(
                "không đọc được %s (%s), coi như không có bia mộ", tombstones.TOMBSTONES_NAME, _error_label(e)
            )
            return []

    async def _restore_scan(self, rd: ReceiveDir) -> list[TempScan]:
        """Bước 2 của `restore`: `scan_temps` qua executor (`trusted_ids` chụp ngay trước khi giao
        việc); hạn `DISK_SYNC_TIMEOUT` bao cả lúc chờ bắt đầu. Quá hạn hay lỗi → rỗng, WARNING."""
        trusted = sorted(self._trusted_ids())
        try:
            job = self._executor.submit(rd.scan_temps, self._identity.device_id, trusted)
        except RuntimeError:  # executor đã shutdown
            return []
        self._track_job(rd, job)  # quá hạn mà vẫn chạy: thư mục này chưa được đóng
        try:
            async with asyncio.timeout(DISK_SYNC_TIMEOUT):
                return await _job_result(job, None)
        except asyncio.CancelledError:
            job.cancel()
            raise
        except Exception as e:  # gồm TimeoutError của `asyncio.timeout`, UnsafeReceiveDirError, OSError
            job.cancel()
            log.warning("không quét được thư mục nhận (%s): không khôi phục lượt nhận nào", _error_label(e))
            return []

    async def _restore_open(self, rd: ReceiveDir, scans: list[TempScan]) -> list[ResumeHandle]:
        """Bước 4 của `restore`: `open_for_resume` song song cho mỗi lượt trong `scans`.

        Mỗi lượt có `threading.Event` `stop` riêng (`abort_now` đặt) và hạn `DISK_SYNC_TIMEOUT`
        tính từ lúc thread bắt đầu; cả bước có hạn tổng `DISK_SYNC_TIMEOUT × ⌈k / DISK_THREADS⌉`
        bao cả lúc chờ bắt đầu. Lượt quá hạn hay lỗi bị bỏ, để nguyên trên đĩa: việc chưa bắt đầu
        bị hủy; việc đang chạy được `stop`, kết quả tới muộn bị đóng (`close_temp`) sau `settled()`.
        Lỗi chỉ log INFO (`transfer_id[:8]` + loại lỗi).
        """
        jobs: list[tuple[TempScan, DiskJob[ResumeHandle], threading.Event]] = []
        for scan in scans:
            stop = threading.Event()
            try:
                job = self._executor.submit(functools.partial(rd.open_for_resume, scan, stop=stop))
            except RuntimeError:  # executor đã shutdown
                break
            self._track_job(rd, job)
            self._restore_stops.add(stop)
            jobs.append((scan, job, stop))
        handles: dict[str, ResumeHandle] = {}

        async def open_one(scan: TempScan, job: DiskJob[ResumeHandle], stop: threading.Event) -> None:
            label = scan.transfer_id[:8]
            try:
                handles[scan.transfer_id] = await _job_result(job, DISK_SYNC_TIMEOUT)
            except DiskTimeout:
                stop.set()
                log.info("mở lại lượt %s quá %g s: bỏ qua, để nguyên trên đĩa", label, DISK_SYNC_TIMEOUT)
            except (NotResumableError, StorageError, ValueError, OSError, _JobDropped) as e:
                log.info("không mở lại được lượt %s: %s", label, _error_label(e))
            except Exception:
                log.exception("lỗi khi mở lại lượt %s", label)

        completed = False
        try:
            rounds = math.ceil(len(jobs) / max(1, diskio.DISK_THREADS))
            try:
                async with asyncio.timeout(DISK_SYNC_TIMEOUT * rounds):
                    await asyncio.gather(*(open_one(*item) for item in jobs))
            except TimeoutError:
                log.info("mở lại lượt nhận dở quá hạn tổng: bỏ qua các lượt chưa xong")
            completed = True
        finally:
            for scan, job, stop in jobs:
                self._restore_stops.discard(stop)
                handle = handles.get(scan.transfer_id)
                if handle is not None:
                    if not completed:  # bị hủy trước khi trao cho engine: chỉ đóng handle
                        close = self._close_temp(rd, handle.temp)
                        self._spawn(close, "transfer-restore-close", disk=True, rd=rd)
                    continue
                if job.cancel():  # chưa bắt đầu: bỏ
                    continue
                stop.set()
                self._spawn(self._close_late_handle(rd, job), "transfer-restore-late", disk=True, rd=rd)
        return [handles[scan.transfer_id] for scan, _, _ in jobs if scan.transfer_id in handles]

    async def _close_late_handle(self, rd: ReceiveDir, job: DiskJob[ResumeHandle]) -> None:
        """`open_for_resume` đã bị bỏ (quá hạn): chờ việc thật sự xong, đóng handle nếu nó mở được.

        `rd`: thư mục nhận của lần khôi phục (thư mục nhận hiện tại có thể đã đổi).
        """
        await job.settled()
        handle = await _late_result(job)
        if handle is not None:
            await self._close_temp(rd, handle.temp)

    def _restore_apply(
        self,
        rd: ReceiveDir | None,
        own: str,
        records: list[TombstoneRecord],
        handles: list[ResumeHandle],
        extra: list[RestoredTombstone],
        done: list[RestoredDone],
    ) -> bool:
        """Bước 5 của `restore`: một khối đồng bộ, không `await` (mục “Khôi phục” ở docstring module).

        Trả True khi engine đã nạp bia mộ (kể cả bia mộ `expired` của lượt thừa); False khi node
        đang đóng hay cả hai lần `engine.restore` đều lỗi: khi đó không được xóa lượt thừa.
        """
        # `rd`: thư mục `restore` đã mở lại `handles` (None khi không có thư mục nhận).
        if self._closing:
            for handle in handles:
                assert rd is not None
                self._spawn(self._close_temp(rd, handle.temp), "transfer-restore-close", disk=True, rd=rd)
            return False
        wall = _wall_time()
        trusted = self._trusted_ids()
        receives: list[RestoredReceive] = []
        lanes: list[_DiskLane] = []
        senders: set[str] = set()
        for handle in handles:
            record = handle.record
            sender, transfer_id = record.sender, handle.temp.transfer_id
            pair = (sender, transfer_id)
            assert rd is not None
            if sender == own or sender not in trusted or sender in senders or pair in self._lanes:
                self._spawn(self._close_temp(rd, handle.temp), "transfer-restore-close", disk=True, rd=rd)
                continue
            senders.add(sender)
            receives.append(
                RestoredReceive(
                    device_id=sender,
                    offer=record.offer,
                    file_index=handle.file_index,
                    bits=handle.bits,
                    leaves=handle.leaves,  # trao quyền sở hữu cho engine
                    part_blocks=handle.part_blocks,
                    age=max(0.0, wall - handle.last_activity),
                )
            )
            # Hàng đĩa có trước khi thực thi hành động: `RemoveTemp` / `SuspendTemp` của lượt áp
            # vào đúng thư mục đã mở.
            lane = _DiskLane(
                sender, transfer_id, rd=rd, temp=handle.temp, parts={handle.file_index: handle.part}
            )
            self._lanes[pair] = lane
            self._live_lanes.add(lane)
            lanes.append(lane)
            self._spawn(self._run_lane(lane), f"transfer-disk {transfer_id[:8]}", disk=True, rd=rd)
        try:
            stones = tombstones.to_restored(records, trusted, wall)
        except Exception:  # phòng thủ: mục đã qua `TombstoneRecord`, không được lỗi
            log.exception("không đổi được bia mộ đã đọc")
            stones = []
        kept_extra = [s for s in extra if s.device_id != own and s.device_id in trusted]
        stones.extend(kept_extra)
        dones = [d for d in done if d.device_id != own and d.device_id in trusted]
        actions, restored = self._restore_engine(receives, stones, dones, lanes)
        grace = core_transfer.RECONNECT_GRACE
        self._dispatching = True  # callback gọi engine lúc này → hoãn
        try:
            for r in receives:
                key = TransferKey(r.device_id, Direction.RECEIVE, r.offer.transfer_id)
                info = self._engine.info(key)
                if info is not None and r.age < grace:
                    self._emit(TransferResumed(info))
        finally:
            self._dispatching = False
        self._dispatch_now(actions)
        self._drain_deferred()
        if restored and kept_extra:
            self._tomb_dirty = True
            self._schedule_tombstone_snapshot()
        return restored

    def _restore_engine(
        self,
        receives: list[RestoredReceive],
        stones: list[RestoredTombstone],
        dones: list[RestoredDone],
        lanes: list[_DiskLane],
    ) -> tuple[list[TransferAction], bool]:
        """`engine.restore` trực tiếp (không qua `_run`) → (hành động, engine đã nạp bia mộ chưa).

        Ném lỗi → gọi lại đúng một lần không kèm lượt nhận dở, rồi đóng các hàng vừa dựng kiểu tạm
        dừng (`close_temp`, không xóa gì). Cả hai lần đều lỗi → `([], False)`: bên gọi không xóa
        lượt thừa và không ghi `tombstones.json` (không đè file bằng bảng rỗng).
        """
        try:
            actions = self._engine.restore(
                receives=receives, tombstones=stones, done=dones, now=self._loop.time()
            )
            return actions, True
        except RuntimeError:
            # Engine đã có lời gọi khác trước `restore` (không được xảy ra: `restore` chạy trước khi mở cổng).
            log.error("TransferEngine đã chạy trước restore(): không khôi phục được gì")
            actions, ok = [], False
        except Exception:
            log.exception("TransferEngine.restore ném lỗi; khôi phục lại không kèm lượt nhận dở")
            try:
                actions = self._engine.restore(
                    receives=(), tombstones=stones, done=dones, now=self._loop.time()
                )
                ok = True
            except Exception:
                log.exception("TransferEngine.restore ném lỗi lần hai")
                actions, ok = [], False
        for lane in lanes:
            lane.suspended = True
            self._close_lane(lane)
        return actions, ok

    async def _discard_temp(self, rd: ReceiveDir, transfer_id: str) -> None:
        """Lượt nhận dở thừa của một máy gửi (`restore`): `discard_temp`, chờ `settled()`; lỗi → INFO."""
        try:
            await self._discard_temp_job(rd, transfer_id)
        finally:
            self._discarding.discard(transfer_id)

    async def _discard_temp_job(self, rd: ReceiveDir, transfer_id: str) -> None:
        discard = functools.partial(rd.discard_temp, transfer_id, own_device_id=self._identity.device_id)
        try:
            job = self._executor.submit(discard)
        except RuntimeError:  # executor đã shutdown
            return
        await job.settled()
        if not job.started:
            return
        try:
            await job.result(None)
        except Exception as e:
            log.info("không xóa được lượt nhận dở thừa %s: %s", transfer_id[:8], _error_label(e))

    # ---- Bia mộ (`tombstones.json`) ------------------------------------------------------------

    def _schedule_tombstone_snapshot(self) -> None:
        """Hẹn chụp bảng bia mộ, nếu chưa hẹn và không có lần ghi đang chạy: ngay (`call_soon`), hay
        lúc đủ `TOMBSTONE_MIN_INTERVAL` từ lần ghi trước (`call_later`)."""
        if self._tomb_scheduled or self._tomb_task is not None or self._tomb_stopped:
            return
        self._tomb_scheduled = True
        last = self._tomb_last_write
        delay = 0.0 if last is None else last + TOMBSTONE_MIN_INTERVAL - self._loop.time()
        if delay > 0:
            self._tomb_handle = self._loop.call_later(delay, self._snapshot_tombstones)
        else:
            self._tomb_handle = self._loop.call_soon(self._snapshot_tombstones)

    def _snapshot_tombstones(self, *, flush: bool = False) -> None:
        """Chụp `export_tombstones` (đồng bộ, ngoài lúc thực hiện danh sách hành động) rồi tạo task ghi."""
        self._tomb_scheduled = False
        self._tomb_handle = None
        if self._tomb_task is not None or self._closed or (self._tomb_stopped and not flush):
            return
        self._tomb_dirty = False
        try:
            items = self._engine.export_tombstones(self._loop.time())
        except Exception:
            log.exception("TransferEngine.export_tombstones ném lỗi")
            return
        wall = _wall_time()
        self._tomb_task = asyncio.create_task(
            self._write_tombstones(items, wall), name=f"{_TASK_NAME}.transfer-tombstones"
        )

    async def _write_tombstones(self, items: tuple[RestoredTombstone, ...], wall: float) -> None:
        """Một lần ghi `tombstones.json` (mã hóa trong thread). Luôn chờ việc `settled` trước khi cho
        lần ghi sau (`atomic.write_atomic` dùng tên `.tmp` cố định); còn thay đổi thì hẹn lần sau.

        Ghi lỗi: đánh dấu lại là chưa ghi (`_tomb_dirty`) nhưng không tự hẹn thử lại, để không lặp
        lỗi mãi; lần đổi sau hay `_flush_tombstones` lúc đóng thử lại (như `HistoryStore._write`).
        Quá hạn thì không đánh dấu: việc vẫn có thể xong muộn."""
        failed = False
        try:
            try:
                job = self._executor.submit(_encode_and_save, self._config_dir, items, wall)
            except RuntimeError:  # executor đã shutdown
                log.warning("không ghi được %s: node đã đóng", tombstones.TOMBSTONES_NAME)
                return
            self._tomb_job = job
            try:
                await _job_result(job, DISK_OP_TIMEOUT)
            except DiskTimeout:
                log.warning("ghi %s quá %g s", tombstones.TOMBSTONES_NAME, DISK_OP_TIMEOUT)
            except _JobDropped:
                return
            except Exception as e:
                log.warning("không ghi được %s: %s", tombstones.TOMBSTONES_NAME, _error_label(e))
                failed = True
            await job.settled()
            self._tomb_last_write = self._loop.time()
        finally:
            if self._tomb_task is asyncio.current_task():
                self._tomb_task = None
        if failed and not self._tomb_dirty:
            # Ảnh chụp này chưa lên đĩa: chờ lần đổi sau hay lúc đóng, không hẹn ngay.
            self._tomb_dirty = True
            return
        if self._tomb_dirty:
            self._schedule_tombstone_snapshot()

    def _stop_tombstones(self) -> None:
        """Không hẹn ghi bia mộ nữa (xả lúc đóng, hay `abort_now`); hủy lần hẹn đang chờ."""
        self._tomb_stopped = True
        self._tomb_scheduled = False
        handle, self._tomb_handle = self._tomb_handle, None
        if handle is not None:
            handle.cancel()

    async def _flush_tombstones(self) -> None:
        """`close()`: ghi ảnh chụp cuối của bảng bia mộ, toàn bộ trong `TOMBSTONE_FLUSH_TIMEOUT`.

        Chờ lần ghi đang chạy `settled`; còn thay đổi chưa ghi thì chụp và ghi ngay (bỏ khoảng cách
        `TOMBSTONE_MIN_INTERVAL`). Quá hạn: việc chưa chạy bị bỏ, việc đang chạy để nguyên trong
        thread, **không** ghi lần hai (hai lần ghi chồng lên cùng `tombstones.json.tmp`), WARNING.
        """
        self._stop_tombstones()
        try:
            async with asyncio.timeout(TOMBSTONE_FLUSH_TIMEOUT):
                task = self._tomb_task
                if task is not None:
                    await asyncio.wait({task})  # không hủy task khi hết hạn
                if self._tomb_task is None and self._tomb_dirty:
                    self._snapshot_tombstones(flush=True)
                    task = self._tomb_task
                    if task is not None:
                        await asyncio.wait({task})
        except TimeoutError:
            job = self._tomb_job
            if job is not None:
                job.cancel()  # chỉ có tác dụng khi việc chưa bắt đầu
            task = self._tomb_task
            if task is not None:
                task.cancel()  # chỉ thôi chờ: không có lần ghi nào sau đó
            log.warning(
                "ghi %s chưa xong sau %g s khi đóng", tombstones.TOMBSTONES_NAME, TOMBSTONE_FLUSH_TIMEOUT
            )
