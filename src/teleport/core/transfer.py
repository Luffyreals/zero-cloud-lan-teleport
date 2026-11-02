"""Máy trạng thái truyền file (sans-IO): gửi, nhận, đồng bộ lại, gửi lại khối lỗi.

Đặc tả ở docs/protocol.md mục 3.3 (kiểm so với `offer`), 4.1–4.4 và 6.2–6.3. Module không
mở socket, không đọc/ghi file, không xem đồng hồ: tầng `app` đưa sự kiện (kết nối điều khiển
lên/mất, message truyền file, kết nối dữ liệu, kết quả đọc khối, ghi đĩa, đọc lại, đổi tên,
quyết định của người dùng, hẹn giờ) cùng thời gian monotonic `now` vào **một**
`TransferEngine` cho cả node, rồi thực hiện các hành động nó trả về. Payload không bao giờ đi
qua đây, chỉ `(index, sha256)`. Engine giữ mọi chính sách (kiểm `data_open`, `seq`, lịch thử
lại, nhịp `fsync`, dung lượng đã hứa, luật khối sai, bia mộ, chờ nối lại); `app` chỉ thực thi.

Hợp đồng thực thi (bên gọi, kể cả bộ mô phỏng của test, phải theo đúng):

1. Gọi engine đồng bộ ngay khi sự kiện xảy ra và thực hiện danh sách hành động **theo đúng
   thứ tự**, không `await` xen giữa lời gọi và các hành động quyết định. **Không gọi lồng
   nhau:** trong lúc đang thực hiện một danh sách thì không gọi phương thức nào của engine;
   kết quả của `AskUser` (kể cả tự nhận), `CheckSpace`, `CheckSource`, thao tác đĩa và
   `OpenData` được giao sau (`loop.call_soon` hoặc một hàng sự kiện).
2. `OpenData` thành công → `outgoing_data`; thất bại, kể cả hết hạn mở → `outgoing_data_failed`.
   Kết nối dữ liệu đi vào đã qua kiểm tin cậy → `incoming_data`, gọi trước `await` đầu tiên.
3. `SendBlocks`: với mỗi `i` trong `have.missing()`, đọc khối và băm trong luồng riêng, gọi
   `block_read`; kết quả có `CloseData` của kết nối đó (hay kết nối đã đóng) → dừng, không ghi
   khung; không thì ghi khung (qua giới hạn tốc độ, `teleport.core.ratelimit`). Hết danh sách →
   đóng gọn → `data_closed(finished=True)`; đứt hay lỗi ghi → `data_closed(finished=False)`;
   lỗi đọc nguồn → `source_failed(changed=False)`; đọc thiếu byte hay không còn là file thường
   → `source_failed(changed=True)`.
4. `ReceiveBlocks`: lặp đọc khung; header sai → `block_bad` rồi dừng; hash payload sai →
   `block_bad`, đóng, dừng; khớp → `block_received`, và chỉ ghi payload khi kết quả có
   `WriteBlock` đúng chỉ số đó; đứt → `data_closed`.
5. Hành động đĩa của một lượt chạy theo **một hàng FIFO** (`CreateTemp`, `OpenPart`,
   `WriteBlock`, `SyncPart`, `ClearBlocks`, `Reread`, `Finalize`, `SuspendTemp`, `RemoveTemp`);
   kết quả báo lại đúng thứ tự (`temp_created`, `synced`, `reread_done`, `finalized`):
   `CreateTemp` thành công → `temp_created`, báo trước kết quả của mọi thao tác đứng sau nó trong
   hàng; `CreateTemp` quá hạn rồi xong muộn thì không báo. Thao tác lỗi →
   `storage_failed(op)` (`CreateTemp` gặp thư mục tạm đã có → `storage_failed(CREATE_TEMP,
   detail=TEMP_EXISTS)`; thư mục nhận đã mất, không tạo lại được → `detail=RECEIVE_DIR_MISSING`)
   rồi bỏ các thao tác còn lại của lượt, trừ `SuspendTemp` và `RemoveTemp`.
   Gặp `RemoveTemp`: bỏ mọi thao tác chưa bắt đầu (kể cả `CreateTemp`, `Finalize`), đặt `stop`
   cho `Reread` đang chạy, chờ thao tác đang chạy xong rồi mới xóa thư mục tạm mà **chính lượt
   đó** đã tạo (đối tượng `CreateTemp` trả về, không suy lại đường dẫn từ `transfer_id`: thiết bị
   khác có thể dùng cùng `transfer_id`); chưa có thư mục tạm (`CreateTemp` lỗi hay chưa chạy) thì
   không làm gì; `keep_record` thì giữ lại `transfer.json`. Gặp `SuspendTemp`: `Finalize` và
   `Reread` chưa bắt đầu bị bỏ (lượt báo tạm dừng không được xong ngầm trên đĩa); các thao tác
   khác đứng trước (`CreateTemp`, `OpenPart`, `WriteBlock`, `SyncPart`, `ClearBlocks`) chạy xong;
   `Reread` đang chạy được dừng như với `RemoveTemp` (đọc lại không đổi gì trên đĩa); rồi chỉ
   đóng handle, không xóa gì. Thao tác bị bỏ hay bị dừng không báo gì. `Finalize` đang chạy thì
   chạy tới cùng.
6. `Reread`: app đọc lại `.part` trong luồng riêng, so hash từng khối với `leaves` để ra `bad`
   (các chỉ số khác nhau, tăng dần); `bad` rỗng thì `root = merkle_root(leaves)`, không thì
   `root = None`; báo `reread_done(bad, root)`. `CheckSource`: `stat` file nguồn (file thường)
   và `merkle_root(leaves)` → `source_checked(size, mtime_ms(st_mtime_ns), root)` hoặc
   `source_failed`. `CheckSpace` → `space_checked(free, max, check_id=CheckSpace.check_id)` trên
   thư mục nhận chụp lúc giao việc, lỗi → `space_checked(None, None, check_id=...)`. `AskUser` →
   `decide`. Đổi thư mục nhận (chỉ khi không `has_accepted_receives()`) → `recheck_space`.
7. Gọi `tick(now)` lúc `next_wakeup()`; gọi sớm hay thừa đều vô hại.
8. Message của một kết nối điều khiển chỉ được giao sau `control_up` của kết nối đó.

Bất biến bên gọi cho phần bền vững (engine không ghi đĩa: `app` lưu trạng thái và đưa lại khi
khởi động bằng `restore`; định dạng ở docs/architecture.md mục 4):

9. `OpenPart` tạo `.part` rỗng **và** header `.state` của file đó. `CreateTemp` ghi `transfer.json`
   từ `CreateTemp.offer` cùng thư mục tạm. `RemoveTemp(keep_record=True)` (lượt DONE) giữ lại
   `transfer.json` của lượt (protocol §6.3), xóa phần còn lại.
10. `synced` chỉ được báo sau khi bản ghi `MARK` của lô đã bền: `fsync` `.part` → nối `MARK`
    (từ `SyncPart.blocks`) → `fsync` `.state` → `synced`. `ClearBlocks` nối `CLEAR` (hay
    `CLEAR_ALL` khi `indices` là None), không cần `fsync` riêng; nó đứng trong hàng FIFO trước
    `SyncPart` kế tiếp nên `fsync` của `MARK` sau làm nó bền theo.
11. `restore` là lời gọi **đầu tiên** của engine (trước mọi `control_up`), đúng một lần, kể cả khi
    không có gì để khôi phục; gọi sau lời gọi khác → RuntimeError. Lượt khôi phục sở hữu thư mục
    tạm mà app đã mở lúc khôi phục (không có `CreateTemp`): `RemoveTemp`/`SuspendTemp` của nó áp
    vào thư mục đó, kể cả `RemoveTemp` mà `restore` phát cho lượt nhận trùng một bia mộ còn hạn
    (lượt đó không có trong engine). `RestoredReceive.leaves` là `bytearray` thì engine giữ chính
    nó: app trao quyền sở hữu và không dùng lại sau `restore`.
12. `TombstonesChanged`: chụp `export_tombstones(now)` **ngoài** lúc đang thực hiện danh sách
    hành động (hẹn bằng `loop.call_soon` hay hàng `_deferred`), rồi mới ghi; gộp nhiều lần báo
    thành một lần ghi được.

Thứ tự hành động được bảo đảm (chỉ những thứ tự này):

- G1: `SendMessage` theo đúng thứ tự gửi. Trong `control_up`: `cancel` của bia mộ chưa gửi →
  `offer` của mọi lượt → `complete`; `accept` trước `resume` của cùng lượt (kể cả trong
  `temp_created`); `cancel` trước
  `CloseData` khi từ chối `data_open` của lượt có bia mộ hay lượt không biết.
- G2: `CreateTemp` trước `OpenPart`; `WriteBlock` trước `SyncPart` chứa nó; `ClearBlocks` (phát
  trong `reread_done`) trước `SyncPart` kế tiếp của file đó; `SuspendTemp` và `RemoveTemp` sau mọi
  hành động đĩa khác của lượt.
- G3: `OpenData` của một `resume` đứng sau `SendMessage(resume)` đó.
- G4: `CloseData` của kết nối dữ liệu cũ đứng trước `SendBlocks`/`ReceiveBlocks` trên kết nối
  mới của cùng lượt.
- G5: các `Report` đứng cuối danh sách; trong đó `StatusChanged` đứng sau mọi `Report` khác.

Kiểm tham số theo thứ tự: kiểu và miền tĩnh (sai → ném, kể cả khi sự kiện nhắc tới thứ engine
không biết) → tra trạng thái (không khớp → `[]`; riêng sự kiện khối với `data_id` không còn
theo dõi → `[CloseData]`) → ràng buộc phụ thuộc trạng thái (sai → ValueError) → ghi `now` rồi
đổi trạng thái. Ném lỗi thì trạng thái giữ nguyên, kể cả mốc `now`.

Bẫy:

- Hash lần đọc đầu của mỗi khối ở bên gửi là **bất biến**: đọc lại ra hash khác →
  `cancel{source_changed}`. Nhờ vậy `leaves` đưa thẳng sang luồng khác là an toàn.
- `Reread.leaves` và `CheckSource.leaves` là **chính** `bytearray` của engine, không phải bản
  chép: engine không sửa nó trong lúc VERIFYING hay sau khi đã ghi (bên gửi), app không được sửa.
- `fsync` trước `resume`: bit chỉ bật ở `synced`, và bên nhận đẩy lô còn lại rồi chờ `synced`
  trước khi gửi `resume`, nên `resume` không bao giờ xin lại khối đã ghi. Từ lúc xin `resume`
  mới, `resume` cũ hết hiệu lực: kết nối dữ liệu của nó bị từ chối, kể cả trong lúc chờ `fsync`.
- Bên nhận là server không có hẹn giờ nào khác để biết bên gửi đã ghi vào một kết nối bị cắt
  trước khi tới đây: nó chờ `data_open` khớp `resume` tới `DATA_OPEN_WAIT`, quá hạn thì hẹn
  `resume` mới theo lịch thử lại. Lần quá hạn đó không tăng `open_failures` (chỉ client mở kết
  nối dữ liệu nên chỉ client báo `DataUnreachable` và sang RECONNECTING, protocol §4.1).
- `RemoveTemp` chỉ khi lượt sở hữu thư mục tạm: `CreateTemp` lỗi thì không bao giờ xóa thư mục
  (có thể là của lượt khác mang cùng `transfer_id`).
- Bên nhận chỉ gửi `accept` và `resume` đầu tiên của một lượt sau `temp_created` (thư mục tạm và
  `transfer.json` đã bền). Trước đó `offer` gửi lại → im lặng, `complete` → `cancel{error}` + bia
  mộ (như `complete` của lượt chưa chấp nhận), `data_open` → `CloseData`; `resume` đã xin được giữ
  tới `temp_created` (hay `control_up` sau đó). Nhờ vậy sập trước lúc đó thì máy gửi chưa có gì
  của lượt, và `offer` gửi lại sau khi khởi động lại được xét như `offer` mới.
- Hạn chót chỉ được xử lý trong `tick` (hạn ≤ `now`); lời gọi khác không tự xử lý, kể cả khi
  đã quá hạn. Ngoại lệ duy nhất: `control_up` cho hết hạn trước (như `tick`) các lượt khôi phục
  có tuổi ≥ `RECONNECT_GRACE` của thiết bị đó, để Q3 không phụ thuộc thứ tự gọi. TTL của bảng nhớ
  được kiểm lười lúc tra.
- Chờ nối lại (protocol §6.2): còn lượt với một máy mà không có kết nối điều khiển (mất kết nối,
  hoặc `send` khi chưa có) thì ghi mốc `offline_since`; `tick` lúc `now ≥ offline_since +
  RECONNECT_GRACE` (24 h) kết thúc mọi lượt với máy đó bằng `expired`, không sớm hơn. `control_up`
  hay hết lượt thì xóa mốc, nên mỗi lần mất kết nối được chờ đủ hạn từ đầu. Hạn đo bằng đồng hồ
  monotonic của node (`loop.time()`): trên Linux/macOS đồng hồ này không chạy khi máy ngủ, nên
  tính theo giờ thật lượt có thể chờ lâu hơn 24 h. `REMEMBER_TTL` dài hơn hạn này (comment ở hằng).
- Trên đường đi của từng khối (`block_received`, `synced`, `block_read`) và khi tính trạng thái
  không gọi `Bitfield.count()`/`all_set()`/`missing()`: dùng bộ đếm O(1). O(n) chỉ một lần mỗi
  `resume` (file 4 TiB có 4 194 304 khối) và một lần mỗi lượt nhận được `restore`.
- Engine chỉ biết thời gian monotonic; `app` đổi mốc giờ tường trên đĩa ra **tuổi** (giây, ≥ 0)
  trước khi `restore`, và `export_tombstones` trả tuổi. Mục nhớ khôi phục được xếp theo tuổi giảm
  dần với `written_at = now − tuổi`, vì bảng nhớ coi thứ tự chèn là thứ tự `written_at`.
- Lượt nhận khôi phục có `offline_since = now − tuổi`: tuổi ≥ `RECONNECT_GRACE` thì hết hạn ở
  `tick` đầu tiên hay `control_up` đầu tiên của thiết bị đó, cái nào tới trước (`RemoveTemp` +
  bia mộ `expired` chưa gửi; trong `control_up` thì `cancel{expired}` được gửi ngay sau đó).
- Tạm dừng (`suspend_receiving`, lúc đóng node có trật tự) không phải hủy: không `cancel`, không
  bia mộ, thư mục tạm còn nguyên cho lần chạy sau; engine thôi nhận `offer` mới (`receiving` =
  False). Engine nhớ khóa của lượt tạm dừng tới hết đời
  của nó để im lặng với `offer`, `complete`, `cancel` và `data_open` của lượt đó (máy gửi phải
  thấy mất kết nối rồi nối lại, không phải `reject{not_receiving}` hay `cancel{unknown_transfer}`).
- Bia mộ và lượt đã xong được lưu xuống đĩa (`tombstones.json`, `transfer.json`); `reject` đã nhớ
  chỉ nằm trong RAM (protocol §6.3).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum

from teleport.core.bitfield import Bitfield
from teleport.core.blocks import BLOCK_SIZE, DIGEST_SIZE, MAX_BLOCKS, MAX_FILE_SIZE, block_count
from teleport.core.filenames import dedupe_offer_names
from teleport.core.messages import (
    MAX_OFFER_FILES,
    MAX_SAFE_INTEGER,
    Accept,
    Cancel,
    CancelReason,
    Complete,
    DataOpen,
    FileEntry,
    MessageError,
    Offer,
    Reject,
    RejectReason,
    Resume,
    Verified,
    validate_device_id,
    validate_transfer_id,
)

# Đọc lúc dùng để test chỉnh được bằng monkeypatch. Thời gian tính bằng giây.
SYNC_EVERY = 16  # protocol §4.3: `fsync` `.part` mỗi 16 khối (và khi đủ file)
MAX_BAD_BLOCKS = 3  # protocol §4.2: lần khối sai liên tiếp thứ 4 → hủy
MAX_VERIFY_FAILURES = 3  # protocol §4.4 bước 5: lần đọc lại / Merkle sai thứ 4 → hủy
MAX_QUEUED_OFFERS = 8  # protocol §3.3, §4.1: `offer` chưa trả lời mỗi thiết bị
MAX_PENDING_DATA = 2  # protocol §4.1: kết nối dữ liệu chờ `resume` mỗi thiết bị
DATA_OPEN_WAIT = 10.0  # protocol §4.1: chờ `resume` khớp `data_open`
DATA_RETRY_BASE = 1.0  # protocol §4.1 → lịch §6.2: 1, 2, 4… giây
DATA_RETRY_MAX = 30.0  # … tối đa 30 s
DATA_FAIL_REPORT_AFTER = 3  # protocol §4.1: báo tường lửa sau 3 lần mở thất bại liên tiếp
RECONNECT_GRACE = 86400.0  # protocol §6.2: chờ nối lại kết nối điều khiển tối đa 24 h
# protocol §6.3: giữ bia mộ / `reject` / lượt đã xong. Phải dài hơn hạn nối lại của máy kia: máy
# đó tính hạn từ lúc nó phát hiện mất kết nối (muộn hơn máy này tới `keepalive.DEAD_AFTER`) và
# còn thử lại theo lịch §6.2, nên bằng đúng `RECONNECT_GRACE` thì `offer` gửi lại sát mốc bị coi
# là mới (`receive --yes` nhận lại lượt đã hủy). Một giờ dư phủ cả hai độ lệch. Vá
# `RECONNECT_GRACE` bằng monkeypatch không đổi hằng này (tính lúc import).
REMEMBER_TTL = RECONNECT_GRACE + 3600.0
MAX_REMEMBERED = 1024  # protocol §6.3: số mục nhớ tối đa mỗi thiết bị

_MAX_RETRY_EXPONENT = 20  # chặn số mũ của lịch thử lại, như `core.links`


class Direction(StrEnum):
    """Chiều của lượt truyền, nhìn từ máy này."""

    SEND = "send"
    RECEIVE = "receive"


class TransferStatus(StrEnum):
    """Trạng thái của lượt chưa kết thúc (mvp F5)."""

    QUEUED = "queued"  # chờ lượt trước cùng thiết bị, cùng chiều
    WAITING = "waiting"  # chờ máy kia hay người dùng trả lời `offer`
    TRANSFERRING = "transferring"
    VERIFYING = "verifying"  # bên nhận đang đọc lại hay đổi tên
    RECONNECTING = "reconnecting"  # mất kết nối điều khiển, hoặc không mở được kết nối dữ liệu


class Outcome(StrEnum):
    DONE = "done"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"  # `suspend_receiving`: lượt nhận dừng, thư mục tạm giữ cho lần chạy sau


class FailureDetail(StrEnum):
    """Nguyên nhân cụ thể của `cancel{error}` do máy này phát hiện."""

    DISK = "disk"
    TEMP_EXISTS = "temp_exists"  # thư mục tạm của lượt đã có sẵn mà không dùng tiếp được
    RECEIVE_DIR_MISSING = "receive_dir_missing"  # thư mục nhận đã mất và không tạo lại được
    CORRUPT_BLOCKS = "corrupt_blocks"
    VERIFY_FAILED = "verify_failed"
    PROTOCOL = "protocol"
    SOURCE_READ = "source_read"


# Nguyên nhân chỉ `storage_failed` với `CREATE_TEMP` mới mang.
_CREATE_TEMP_DETAILS = frozenset({FailureDetail.TEMP_EXISTS, FailureDetail.RECEIVE_DIR_MISSING})


class DiskOp(StrEnum):
    """Thao tác đĩa bị lỗi, báo qua `storage_failed`."""

    CREATE_TEMP = "create_temp"
    OPEN_PART = "open_part"
    WRITE = "write"
    SYNC = "sync"
    REREAD = "reread"
    FINALIZE = "finalize"


class TransferIdInUse(ValueError):
    """`send()`: `transfer_id` đã có trong bảng của thiết bị đó (protocol §6.3, gạch “Khóa”)."""


TransferMessage = Offer | Accept | Reject | Resume | Complete | Verified | Cancel
_TRANSFER_MESSAGE_TYPES = (Offer, Accept, Reject, Resume, Complete, Verified, Cancel)


@dataclass(frozen=True, slots=True)
class TransferKey:
    """Khóa của lượt truyền (protocol §6.3): thiết bị, chiều, `transfer_id`."""

    device_id: str
    direction: Direction
    transfer_id: str


@dataclass(frozen=True, slots=True)
class TransferInfo:
    """Bản chụp một lượt truyền cho giao diện / CLI.

    `done_bytes`: bên nhận là byte đã bền (file đã `verified` cộng các khối đã `synced` của file
    hiện tại, nhảy bậc theo lô `SyncPart`); bên gửi là byte đã gửi. Lịch sử, resume và CLI dùng
    trường này. `unsynced_bytes` chỉ để hiển thị: bên nhận là byte các khối của file hiện tại đã
    phát `WriteBlock` mà chưa `synced`, bên gửi luôn 0. `done_bytes + unsynced_bytes` ≤
    `total_bytes` nhưng có thể giảm (nối lại bỏ các khối chưa sync, đọc lại thấy khối sai).
    """

    key: TransferKey
    status: TransferStatus  # trong `TransferEnded`: trạng thái ngay trước khi kết thúc
    files: tuple[FileEntry, ...]
    names: tuple[str, ...]  # bên nhận: tên đã làm sạch và khử trùng; bên gửi: tên trong `offer`
    file_index: int  # bên nhận: file hiện tại (0…n); bên gửi: số file đã được `verified`
    done_bytes: int
    total_bytes: int
    unsynced_bytes: int = 0


# ---- Sự kiện báo giao diện -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatusChanged:
    key: TransferKey
    status: TransferStatus


@dataclass(frozen=True, slots=True)
class FileVerified:
    """Một file đã xong. `name`: bên nhận là tên thật cuối cùng; bên gửi là tên trong `offer`."""

    key: TransferKey
    file_index: int
    name: str


@dataclass(frozen=True, slots=True)
class TransferEnded:
    """Lượt kết thúc (đúng một lần mỗi lượt). `info` là bản chụp cuối; `file_index` < n hoặc None."""

    key: TransferKey
    outcome: Outcome
    reason: str | None
    by_peer: bool
    detail: FailureDetail | None
    file_index: int | None
    reject: Reject | None
    info: TransferInfo


@dataclass(frozen=True, slots=True)
class DataUnreachable:
    """Mở kết nối dữ liệu thất bại `DATA_FAIL_REPORT_AFTER` lần liên tiếp (báo tường lửa, mvp mục 8)."""

    device_id: str


TransferEvent = StatusChanged | FileVerified | TransferEnded | DataUnreachable


# ---- Hành động --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SendMessage:
    """Gửi `message` trên kết nối điều khiển `control_id` nếu nó vẫn là kết nối hiện tại; không thì bỏ."""

    device_id: str
    control_id: int
    message: TransferMessage


@dataclass(frozen=True, slots=True)
class OpenData:
    """Mở kết nối dữ liệu tới địa chỉ và cổng của kết nối điều khiển `control_id`, gửi `message`."""

    device_id: str
    control_id: int
    message: DataOpen


@dataclass(frozen=True, slots=True)
class CloseData:
    """Đóng ngay (abort) kết nối dữ liệu `data_id`. Engine đã quên kết nối này."""

    device_id: str
    data_id: int


@dataclass(frozen=True, slots=True)
class SendBlocks:
    """Bên gửi ghi khung cho mọi khối **không** có trong `have`, tăng dần; `have` là bản sao riêng."""

    device_id: str
    data_id: int
    transfer_id: str
    file_index: int
    size: int
    have: Bitfield


@dataclass(frozen=True, slots=True)
class ReceiveBlocks:
    """Bên nhận đọc khung khối trên `data_id` (file `size` byte)."""

    device_id: str
    data_id: int
    transfer_id: str
    file_index: int
    size: int


@dataclass(frozen=True, slots=True)
class CreateTemp:
    """Tạo `.teleport/<transfer_id>/` và ghi `transfer.json` từ `offer`; thư mục đã có thì lỗi."""

    device_id: str
    transfer_id: str
    offer: Offer


@dataclass(frozen=True, slots=True)
class OpenPart:
    """Tạo `<file_index>.part` rỗng cho file `size` byte và header `<file_index>.state`."""

    device_id: str
    transfer_id: str
    file_index: int
    size: int


@dataclass(frozen=True, slots=True)
class WriteBlock:
    """Ghi payload vừa nhận của khối `index` vào `.part`, ở vị trí `index × BLOCK_SIZE`."""

    device_id: str
    transfer_id: str
    file_index: int
    index: int


@dataclass(frozen=True, slots=True)
class SyncPart:
    """`fsync` `.part` (gồm mọi `WriteBlock` trước nó), nối `MARK` của lô vào `.state`, `fsync` nó.

    `blocks` là `(index, sha256)` của lô; `synced` chỉ sau khi `MARK` đã bền.
    """

    device_id: str
    transfer_id: str
    file_index: int
    token: int
    blocks: tuple[tuple[int, bytes], ...]


@dataclass(frozen=True, slots=True)
class ClearBlocks:
    """Nối `CLEAR` các khối `indices` (tăng dần) vào `.state`; `indices` None → `CLEAR_ALL`.

    Không báo kết quả; lỗi ghi → `storage_failed(op=SYNC)` như lỗi ghi `.state` khác.
    """

    device_id: str
    transfer_id: str
    file_index: int
    indices: tuple[int, ...] | None


@dataclass(frozen=True, slots=True)
class Reread:
    """Đọc lại `.part`, so với `leaves` (chính bytearray của engine, không được sửa)."""

    device_id: str
    transfer_id: str
    file_index: int
    leaves: bytearray


@dataclass(frozen=True, slots=True)
class Finalize:
    """Đổi tên không ghi đè sang `name` hoặc `name (n)`; đặt `mtime` (ms), `utime` lỗi thì bỏ qua."""

    device_id: str
    transfer_id: str
    file_index: int
    name: str
    mtime: int


@dataclass(frozen=True, slots=True)
class RemoveTemp:
    """Xóa thư mục tạm `.teleport/<transfer_id>/` mà chính lượt này đã tạo (không có thì bỏ qua).

    `keep_record` (lượt DONE): giữ `transfer.json` để trả lời `offer`/`complete` gửi lại sau khi
    khởi động lại (protocol §6.3); bản ghi đó được dọn sau `REMEMBER_TTL`.
    """

    device_id: str
    transfer_id: str
    keep_record: bool = False


@dataclass(frozen=True, slots=True)
class SuspendTemp:
    """Tạm dừng lượt nhận (`suspend_receiving`): chạy nốt thao tác ghi đứng trước (bỏ `Finalize` /
    `Reread` chưa bắt đầu), rồi chỉ đóng handle.

    Không xóa gì: `.part`, `.state`, `transfer.json` giữ nguyên cho lần `restore` sau.
    """

    device_id: str
    transfer_id: str


@dataclass(frozen=True, slots=True)
class CheckSpace:
    """Lấy dung lượng trống và `max_file_size` của thư mục nhận, rồi `space_checked`.

    `check_id`: số engine cấp cho lần kiểm này (tăng dần); bên gọi trả lại nó trong
    `space_checked` để kết quả của lần kiểm cũ (trước `recheck_space`) bị bỏ.
    """

    device_id: str
    transfer_id: str
    total_size: int
    check_id: int = 0


@dataclass(frozen=True, slots=True)
class AskUser:
    """Hỏi người dùng (hoặc tự nhận nếu đang `--yes`), rồi `decide`. `names` đã làm sạch."""

    device_id: str
    transfer_id: str
    offer: Offer
    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CheckSource:
    """`stat` file nguồn và `merkle_root(leaves)` trong luồng riêng; `leaves` bất biến."""

    device_id: str
    transfer_id: str
    file_index: int
    leaves: bytearray


@dataclass(frozen=True, slots=True)
class TombstonesChanged:
    """Bảng bia mộ đã đổi (thêm, ghi đè, bị đẩy ra, hay cờ `unsent` đổi): lưu lại `tombstones.json`.

    Tối đa một lần mỗi lời gọi. Chụp `export_tombstones` ngoài lúc thực hiện danh sách hành động
    (hợp đồng mục 12). Bia mộ hết TTL không sinh hành động này: bộ đọc bỏ mục quá `REMEMBER_TTL`.
    """


@dataclass(frozen=True, slots=True)
class Report:
    """Báo giao diện / CLI."""

    event: TransferEvent


TransferAction = (
    SendMessage
    | OpenData
    | CloseData
    | SendBlocks
    | ReceiveBlocks
    | CreateTemp
    | OpenPart
    | WriteBlock
    | SyncPart
    | ClearBlocks
    | Reread
    | Finalize
    | SuspendTemp
    | RemoveTemp
    | CheckSpace
    | AskUser
    | CheckSource
    | TombstonesChanged
    | Report
)


# ---- Dữ liệu khôi phục (`restore`, `export_tombstones`) -----------------------------------


@dataclass(frozen=True, slots=True)
class RestoredReceive:
    """Lượt nhận dở đọc lại từ đĩa (`transfer.json` + `.state` của file hiện tại).

    `file_index` < số file (các file trước đã `verified`). `bits` (đúng `block_count(size)` bit) và
    `leaves` (32 byte mỗi khối, hash của khối có bit bật) là trạng thái file hiện tại sau khi
    đọc lại `.state`. `part_blocks`: số khối đầu nằm trọn trong `.part`; mọi bit từ đó trở đi
    phải tắt (app đã xóa bit khối không nằm trọn trong `.part`). `age`: giây từ hoạt động cuối.
    """

    device_id: str
    offer: Offer
    file_index: int
    bits: Bitfield
    leaves: bytes | bytearray
    part_blocks: int
    age: float


@dataclass(frozen=True, slots=True)
class RestoredTombstone:
    """Một bia mộ (protocol §6.3): `age` là giây từ lúc lập hay ghi đè."""

    device_id: str
    direction: Direction
    transfer_id: str
    reason: str
    unsent: bool
    age: float


@dataclass(frozen=True, slots=True)
class RestoredDone:
    """Lượt nhận đã `verified` mọi file (`transfer.json` có `done_at`); `age` là giây từ `done_at`."""

    device_id: str
    offer: Offer
    age: float


# ---- Hàm thuần -------------------------------------------------------------------------------


def check_offer(offer: Offer, *, free_bytes: int | None, max_file_size: int | None) -> Reject | None:
    """`reject` tự động cho `offer` theo chỗ trống, hay None nếu nhận được (protocol §3.3).

    `file_too_large` (file vi phạm đầu tiên) được xét trước `no_space`. `free_bytes` /
    `max_file_size` là None khi không biết. `offer` không phải `Offer` → TypeError; giới hạn
    không phải `int` ≥ 0 (bool bị từ chối) → ValueError.
    """
    if not isinstance(offer, Offer):
        raise TypeError("offer phải là Offer")
    free_bytes = _check_optional_size("free_bytes", free_bytes)
    max_file_size = _check_optional_size("max_file_size", max_file_size)
    if max_file_size is not None:
        for index, entry in enumerate(offer.files):
            if entry.size > max_file_size:
                return Reject(
                    offer.transfer_id,
                    RejectReason.FILE_TOO_LARGE,
                    file_index=index,
                    max_size=max_file_size,
                )
    total = sum(entry.size for entry in offer.files)
    if free_bytes is not None and total > free_bytes:
        return Reject(
            offer.transfer_id,
            RejectReason.NO_SPACE,
            needed=total,
            available=min(free_bytes, MAX_SAFE_INTEGER),
        )
    return None


def mtime_ms(ns: int) -> int:
    """`st_mtime_ns` → `mtime` trên dây: mili giây, âm thành 0, trần `MAX_SAFE_INTEGER`.

    `ns` không phải `int` (bool bị từ chối) → TypeError. Dùng cho cả `offer` lẫn kiểm nguồn.
    """
    if isinstance(ns, bool) or not isinstance(ns, int):
        raise TypeError("ns phải là số nguyên nano giây")
    return max(0, min(ns // 1_000_000, MAX_SAFE_INTEGER))


def _retry_delay(k: int) -> float:
    """Lịch thử lại (protocol §6.2): 1, 2, 4, 8, 16, 30, 30… giây (k ≥ 1)."""
    exponent = min(max(k, 1) - 1, _MAX_RETRY_EXPONENT)
    return min(DATA_RETRY_BASE * 2**exponent, DATA_RETRY_MAX)


def _manifest_digest(offer: Offer) -> bytes:
    """Dấu vân manifest: SHA-256 của JSON chuẩn hóa `[block_size, [[name, size, mtime], …]]`."""
    manifest = [offer.block_size, [[f.name, f.size, f.mtime] for f in offer.files]]
    text = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).digest()


def _block_len(size: int, index: int) -> int:
    """Độ dài khối `index` của file `size` byte (không kiểm tham số: đường đi của từng khối)."""
    return min(BLOCK_SIZE, size - index * BLOCK_SIZE)


def _copy_bitfield(bits: Bitfield) -> Bitfield:
    return Bitfield.from_base64(bits.to_base64(), len(bits))


def _finite_float(value: int | float) -> float | None:
    """`value` đổi sang float nếu hữu hạn; None nếu vô hạn, NaN hay số nguyên quá lớn cho float."""
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def _check_id(name: str, value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} phải là số nguyên ≥ 1")
    return value


def _check_bool(name: str, value: object) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} phải là bool")
    return value


def _check_range(name: str, value: object, hi: int) -> int:
    if type(value) is not int or not 0 <= value <= hi:
        raise ValueError(f"{name} phải là số nguyên 0…{hi}")
    return value


def _check_digest(name: str, value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != DIGEST_SIZE:
        raise ValueError(f"{name} phải là đúng {DIGEST_SIZE} byte")
    return value


def _check_optional_size(name: str, value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} phải là số nguyên ≥ 0 hoặc None")
    return value


def _check_age(name: str, value: object) -> float:
    """Tuổi của dữ liệu khôi phục: số giây hữu hạn ≥ 0 (bool bị từ chối)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} phải là số giây")
    result = _finite_float(value)
    if result is None or result < 0:
        raise ValueError(f"{name} phải là số hữu hạn ≥ 0")
    return result


def _check_items[T](name: str, items: object, cls: type[T]) -> tuple[T, ...]:
    """Dãy (list/tuple) các `cls` của `restore`; kiểu khác → TypeError."""
    if not isinstance(items, list | tuple):
        raise TypeError(f"{name} phải là list hoặc tuple")
    for item in items:
        if not isinstance(item, cls):
            raise TypeError(f"{name} chỉ chứa {cls.__name__}")
    return tuple(items)


def _check_bad(bad: object) -> tuple[int, ...]:
    """Chỉ số khối sai của `reread_done`: list/tuple các `int` ≥ 0 tăng ngặt."""
    if not isinstance(bad, list | tuple):
        raise ValueError("bad phải là list hoặc tuple các chỉ số khối")
    previous = -1
    for index in bad:
        if type(index) is not int or index <= previous:
            raise ValueError("bad phải gồm các số nguyên ≥ 0 tăng ngặt")
        previous = index
    return tuple(bad)


# ---- Trạng thái nội bộ -----------------------------------------------------------------------


class _Default(Enum):
    """Giá trị “dùng `file_index` mặc định” của lượt khi kết thúc (mục 3.9 của spec)."""

    INDEX = 0


class _ConnKind(StrEnum):
    PENDING = "pending"  # bên gửi là server: đã nhận `data_open`, chờ `resume` khớp
    SERVING = "serving"  # bên gửi: đang ghi khối
    RECEIVING = "receiving"  # bên nhận: đang đọc khối


@dataclass(slots=True, eq=False)
class _DataConn:
    data_id: int
    device_id: str
    key: TransferKey
    kind: _ConnKind
    file_index: int
    seq: int  # `resume_seq` mà kết nối phục vụ
    deadline: float = 0.0  # PENDING: hạn chờ `resume`
    cursor: int = -1  # RECEIVING: chỉ số khối cuối đã nhận trên kết nối này
    progressed: bool = False  # RECEIVING: đã mang ít nhất một khối mới


@dataclass(slots=True)
class _Tombstone:
    """Lượt đã hủy hay thất bại. `unsent`: lập lúc không có kết nối điều khiển, chưa gửi `cancel`."""

    reason: str
    unsent: bool
    written_at: float
    order: int


@dataclass(slots=True)
class _RejectMemo:
    """`reject` đã gửi (chiều RECEIVE), để gửi lại đúng nó cho `offer` gửi lại."""

    reject: Reject
    written_at: float
    order: int


@dataclass(slots=True)
class _DoneMemo:
    """Lượt nhận đã `verified` mọi file (chiều RECEIVE)."""

    n_files: int
    manifest_digest: bytes
    written_at: float
    order: int


_Memo = _Tombstone | _RejectMemo | _DoneMemo


class _Memory:
    """Bảng nhớ lượt đã kết thúc của một thiết bị: chỗ duy nhất giữ bia mộ, `reject` đã nhớ và
    lượt đã xong (protocol §6.3). Tối đa `MAX_REMEMBERED` mục; thêm hay ghi đè thì mục thành mới
    nhất; mục có `now − written_at ≥ REMEMBER_TTL` coi như không có và bị xóa lúc tra.

    `now` không giảm, và `restore` chèn mục khôi phục theo tuổi giảm dần với `written_at = now − tuổi`
    ≤ `now`, nên thứ tự trong `OrderedDict` cũng là thứ tự `written_at`.
    """

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: OrderedDict[tuple[Direction, str], _Memo] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, direction: Direction, transfer_id: str, now: float) -> _Memo | None:
        key = (direction, transfer_id)
        memo = self._entries.get(key)
        if memo is not None and now - memo.written_at >= REMEMBER_TTL:
            del self._entries[key]
            return None
        return memo

    def put(self, direction: Direction, transfer_id: str, memo: _Memo) -> bool:
        """Thêm hay ghi đè; True nếu tập bia mộ đổi (bia mộ thêm, bị thay hay bị đẩy ra)."""
        key = (direction, transfer_id)
        old = self._entries.pop(key, None)
        changed = isinstance(memo, _Tombstone) or isinstance(old, _Tombstone)
        self._entries[key] = memo
        while len(self._entries) > max(MAX_REMEMBERED, 0):
            _, evicted = self._entries.popitem(last=False)
            changed = changed or isinstance(evicted, _Tombstone)
        return changed

    def tombstone(self, transfer_id: str, now: float) -> _Tombstone | None:
        """Bia mộ mới nhất của `transfer_id`, xét cả hai chiều."""
        found: _Tombstone | None = None
        for direction in Direction:
            memo = self.get(direction, transfer_id, now)
            if isinstance(memo, _Tombstone) and (found is None or memo.order > found.order):
                found = memo
        return found

    def knows(self, transfer_id: str, now: float) -> bool:
        return any(self.get(direction, transfer_id, now) is not None for direction in Direction)

    def take_unsent(self, now: float) -> list[tuple[str, str]]:
        """`(transfer_id, lý do)` của mọi bia mộ `unsent`, theo thứ tự ghi; xóa cờ của chúng."""
        self.prune(now)
        result: list[tuple[str, str]] = []
        for (_, transfer_id), memo in self._entries.items():
            if isinstance(memo, _Tombstone) and memo.unsent:
                memo.unsent = False
                result.append((transfer_id, memo.reason))
        return result

    def prune(self, now: float) -> None:
        """Bỏ các mục đã hết TTL (nằm ở đầu bảng)."""
        while self._entries:
            key, memo = next(iter(self._entries.items()))
            if now - memo.written_at < REMEMBER_TTL:
                return
            del self._entries[key]

    def tombstones(self, now: float) -> list[tuple[Direction, str, _Tombstone]]:
        """Bia mộ còn hạn theo thứ tự ghi, không sửa bảng (truy vấn thuần)."""
        return [
            (direction, transfer_id, memo)
            for (direction, transfer_id), memo in self._entries.items()
            if isinstance(memo, _Tombstone) and now - memo.written_at < REMEMBER_TTL
        ]


@dataclass(slots=True, eq=False)
class _SendFile:
    """Trạng thái một file ở bên gửi, cấp ở `resume` đầu tiên của file, giải phóng khi `verified`."""

    n: int
    sent: Bitfield  # khối đã qua `block_read` ít nhất một lần
    leaves: bytearray  # hash lần đọc đầu, bất biến sau khi ghi
    sent_count: int = 0
    sent_bytes: int = 0
    root: bytes | None = None
    checking: bool = False  # đang có `CheckSource`


@dataclass(slots=True, eq=False)
class _Latest:
    """`resume` mới nhất của một lượt trên kết nối điều khiển hiện tại (bên gửi)."""

    file_index: int
    seq: int
    have: Bitfield
    full: bool


@dataclass(slots=True, eq=False)
class _Send:
    key: TransferKey
    offer: Offer
    names: tuple[str, ...]
    total_size: int
    verified: bytearray  # 1 byte mỗi file: 1 = đã `verified`
    accepted: bool = False
    verified_count: int = 0
    verified_bytes: int = 0
    states: dict[int, _SendFile] = field(default_factory=dict)
    served: bool = False  # đã từng cấp trạng thái file (đã phục vụ một `resume`)
    latest: _Latest | None = None
    conn: _DataConn | None = None  # kết nối đang phục vụ
    retry_at: float | None = None  # lịch mở lại kết nối dữ liệu
    retry_msg: DataOpen | None = None
    idle_rounds: int = 0
    reported: TransferStatus | None = None


class _Phase(StrEnum):
    QUEUED = "queued"  # trong hàng `offer`, chưa tới lượt
    CHECKING = "checking"  # đầu hàng, đã phát `CheckSpace`
    ASKING = "asking"  # đầu hàng, đã phát `AskUser`
    RUNNING = "running"  # đã chấp nhận


@dataclass(slots=True, eq=False)
class _Recv:
    key: TransferKey
    offer: Offer
    names: tuple[str, ...]
    total_size: int
    phase: _Phase = _Phase.QUEUED
    check_id: int = 0  # `CheckSpace` mới nhất của lượt; kết quả mang số khác bị bỏ
    rechecking: bool = False  # ASKING: đang kiểm lại trên thư mục nhận mới (`recheck_space`)
    accept_pending: bool = False  # người dùng đã bấm Nhận trong lúc `rechecking`
    owns_temp: bool = False
    created: bool = False  # đã `temp_created` (hay từ `restore`): được gửi `accept`/`resume`
    expire_restored: bool = False  # từ `restore` với tuổi ≥ `RECONNECT_GRACE`: hết hạn ở `control_up`
    file_index: int = 0
    verified_bytes: int = 0
    # File hiện tại (mục 3.6–3.8 của spec).
    n_f: int = 0
    size_f: int = 0
    bits: Bitfield = field(default_factory=lambda: Bitfield(0))
    leaves: bytearray = field(default_factory=bytearray)
    have_count: int = 0
    have_bytes: int = 0
    pending: set[int] = field(default_factory=set)  # đã `WriteBlock` mà chưa `synced`
    pending_bytes: int = 0
    unbatched: list[tuple[int, bytes]] = field(default_factory=list)
    batches: dict[int, list[tuple[int, bytes]]] = field(default_factory=dict)  # token → lô
    hw: int = -1  # khối cao nhất đã phát `WriteBlock`
    root: bytes | None = None  # từ `complete`
    bad_count: int = 0
    verify_failures: int = 0
    idle_rounds: int = 0
    want_resume: bool = False  # cần gửi `resume` khi lô cuối `synced`
    sent_resume: bool = False  # đã gửi `resume` trên kết nối điều khiển hiện tại
    # (file, seq, đủ bit) của `resume` đang có hiệu lực trên kết nối hiện tại; None từ lúc xin
    # `resume` mới (kể cả khi còn chờ `fsync`) để `data_open` của `resume` cũ bị từ chối.
    last_resume: tuple[int, int, bool] | None = None
    resume_at: float | None = None  # lịch xin `resume`
    open_wait_at: float | None = None  # máy này là server: hạn chờ `data_open` của `resume` vừa gửi
    rereading: bool = False
    finalizing: bool = False
    conn: _DataConn | None = None  # kết nối đang nhận
    reported: TransferStatus | None = None


_Transfer = _Send | _Recv


@dataclass(slots=True, eq=False)
class _Peer:
    """Trạng thái của một thiết bị: luật cắt ngang của mọi lượt với nó."""

    device_id: str
    control: tuple[int, bool] | None = None  # (control_id, máy này là client)
    next_seq: int = 1  # bên nhận
    max_seq: int = 0  # bên gửi
    pending: list[_DataConn] = field(default_factory=list)  # chờ `resume` (≤ MAX_PENDING_DATA)
    memory: _Memory = field(default_factory=_Memory)
    transfers: dict[tuple[Direction, str], _Transfer] = field(default_factory=dict)  # thứ tự tạo
    offers: list[_Recv] = field(default_factory=list)  # hàng `offer` chưa trả lời, đầu hàng trước
    running: _Recv | None = None  # lượt nhận đang chạy
    offline_since: float | None = None
    open_failures: int = 0
    unreachable_reported: bool = False


class TransferEngine:
    """Máy trạng thái truyền file của một node (sans-IO). Hợp đồng: docstring của module.

    Mọi phương thức sự kiện trả `list[TransferAction]`. `now` là thời gian monotonic (giây),
    không được nhỏ hơn mốc của lời gọi thành công trước đó. Sự kiện nhắc tới thứ engine không
    biết hay đã kết thúc (lượt, token, kết nối điều khiển cũ, `device_id` của chính máy này)
    trả `[]`: đó là chuyện đua bình thường. `restore` phải là lời gọi đầu tiên (hợp đồng mục 11).
    """

    def __init__(self, own_device_id: str, *, receiving: bool) -> None:
        self._own_id = validate_device_id(own_device_id)
        self._receiving = _check_bool("receiving", receiving)
        self._peers: dict[str, _Peer] = {}
        self._transfers: dict[TransferKey, _Transfer] = {}  # lượt chưa kết thúc, thứ tự tạo
        self._conns: dict[int, _DataConn] = {}  # mọi kết nối dữ liệu đang theo dõi
        self._suspended: set[TransferKey] = set()  # lượt nhận đã `suspend_receiving`: im lặng với chúng
        self._last_now: float | None = None  # None: chưa có lời gọi thành công nào (`restore` còn gọi được)
        self._next_token = 1
        self._next_order = 1
        self._next_check_id = 1
        self._actions: list[TransferAction] = []
        self._reports: list[TransferAction] = []
        self._tombstones_changed = False  # lời gọi này đã đổi tập bia mộ → `TombstonesChanged`

    # ---- Truy vấn ------------------------------------------------------------------------

    @property
    def receiving(self) -> bool:
        """Máy này có nhận file không (A3); chỉ áp cho `offer` mới."""
        return self._receiving

    @receiving.setter
    def receiving(self, value: bool) -> None:
        self._receiving = _check_bool("receiving", value)

    def info(self, key: TransferKey) -> TransferInfo | None:
        """Bản chụp lượt `key`; None nếu không biết hoặc đã kết thúc."""
        if not isinstance(key, TransferKey):
            return None
        t = self._transfers.get(key)
        if t is None:
            return None
        return self._info(t, self._status(t, self._has_older_send(t)))

    def transfers(self) -> tuple[TransferInfo, ...]:
        """Mọi lượt chưa kết thúc, theo thứ tự tạo."""
        result: list[TransferInfo] = []
        seen_send: set[str] = set()
        for t in self._transfers.values():
            older = False
            if isinstance(t, _Send):
                older = t.key.device_id in seen_send
                seen_send.add(t.key.device_id)
            result.append(self._info(t, self._status(t, older)))
        return tuple(result)

    def promised_bytes(self) -> int:
        """Số byte đã hứa nhận: lượt đang hỏi người dùng (cả lượt) và lượt đang chạy (phần còn lại)."""
        total = 0
        for t in self._transfers.values():
            if isinstance(t, _Recv):
                if t.phase is _Phase.ASKING:
                    total += t.total_size
                elif t.phase is _Phase.RUNNING:
                    total += t.total_size - t.verified_bytes - t.have_bytes - t.pending_bytes
        return total

    def has_accepted_receives(self) -> bool:
        """Còn lượt nhận đã chấp nhận (kể cả lượt khôi phục, đang nối lại, chưa `temp_created`).

        Lượt nhận đang xếp hàng, đang kiểm chỗ trống hay đang hỏi người dùng không tính: đổi thư
        mục nhận lúc chỉ còn chúng thì gọi `recheck_space`.
        """
        return any(
            isinstance(t, _Recv) and t.phase not in (_Phase.QUEUED, _Phase.CHECKING, _Phase.ASKING)
            for t in self._transfers.values()
        )

    def next_wakeup(self) -> float | None:
        """Hạn sớm nhất cần `tick`; None nếu không có. TTL của bảng nhớ không được tính."""
        times: list[float] = []
        for peer in self._peers.values():
            times.extend(conn.deadline for conn in peer.pending)
            for t in peer.transfers.values():
                if isinstance(t, _Send):
                    if t.retry_at is not None:
                        times.append(t.retry_at)
                    continue
                if t.resume_at is not None:
                    times.append(t.resume_at)
                if t.open_wait_at is not None:
                    times.append(t.open_wait_at)
            if peer.control is None and peer.offline_since is not None and peer.transfers:
                times.append(peer.offline_since + RECONNECT_GRACE)
        return min(times) if times else None

    def export_tombstones(self, now: float) -> tuple[RestoredTombstone, ...]:
        """Mọi bia mộ còn hạn, cả hai chiều, theo thứ tự ghi (cũ trước), kèm tuổi tính theo `now`.

        Truy vấn thuần: không ghi mốc `now`, không sửa bảng (mục hết TTL bị bỏ qua, không bị xóa).
        `now` sai kiểu hay nhỏ hơn mốc của lời gọi trước → như mọi lời gọi khác.
        """
        now = self._check_now(now)
        found: list[tuple[int, RestoredTombstone]] = []
        for device_id, peer in self._peers.items():
            for direction, transfer_id, memo in peer.memory.tombstones(now):
                age = max(0.0, now - memo.written_at)
                item = RestoredTombstone(device_id, direction, transfer_id, memo.reason, memo.unsent, age)
                found.append((memo.order, item))
        found.sort(key=lambda pair: pair[0])
        return tuple(item for _, item in found)

    # ---- Khôi phục, tạm dừng -------------------------------------------------------------

    def restore(
        self,
        *,
        receives: Sequence[RestoredReceive],
        tombstones: Sequence[RestoredTombstone],
        done: Sequence[RestoredDone],
        now: float,
    ) -> list[TransferAction]:
        """Nạp trạng thái đọc lại từ đĩa; phải là lời gọi đầu tiên (sau lời gọi khác → RuntimeError).

        - Bia mộ và lượt đã xong có tuổi ≥ `REMEMBER_TTL` bị bỏ; phần còn lại vào bảng nhớ theo
          tuổi giảm dần (cùng tuổi: lượt đã xong trước bia mộ, rồi theo thứ tự đưa vào), mỗi mục
          `written_at = now − tuổi`. Bảng mỗi thiết bị vẫn có trần `MAX_REMEMBERED` (bỏ mục cũ).
        - Mỗi lượt nhận thành lượt đang chạy (RUNNING), sở hữu thư mục tạm, chưa có kết nối điều
          khiển: `offline_since = now − tuổi`, khối cao nhất đã ghi = `part_blocks − 1`, không phát
          `OpenPart` (`.part` và `.state` đã có). Kết quả có `Report(StatusChanged(RECONNECTING))`
          của nó; lượt đã `temp_created`, nên `control_up` sau đó gửi `accept` rồi `resume` với
          bitfield khôi phục. Tuổi ≥ `RECONNECT_GRACE` → hết hạn ở `tick` đầu tiên hay ở
          `control_up` đầu tiên của thiết bị đó, cái nào tới trước (Q3). `leaves` là `bytearray`
          thì engine giữ chính nó (app không được dùng lại); kiểu khác thì chép.
        - Lượt nhận trùng khóa một bia mộ được khôi phục (đã hủy mà chưa kịp dọn) không được khôi
          phục: chỉ phát `RemoveTemp` cho thư mục tạm app đã mở cho nó (hợp đồng mục 11).

        Sai kiểu dãy hay phần tử → TypeError. ValueError khi: `device_id`/`transfer_id` sai hay là
        máy này; một thiết bị có hơn một lượt nhận; `file_index` ≥ số file; `bits` không phải
        `Bitfield` đúng số khối; `leaves` sai độ dài; `part_blocks` ngoài 0…số khối hay có bit
        bật từ `part_blocks` trở đi; tuổi không phải số hữu hạn ≥ 0; `direction`, `reason`,
        `unsent` của bia mộ sai; lượt nhận trùng khóa một lượt đã xong còn hạn. Không có
        `TombstonesChanged`: bảng vừa nạp đúng bằng thứ đã lưu (trừ mục hết hạn).
        """
        if self._last_now is not None:
            raise RuntimeError("restore phải là lời gọi đầu tiên của TransferEngine")
        recvs = _check_items("receives", receives, RestoredReceive)
        stones = _check_items("tombstones", tombstones, RestoredTombstone)
        dones = _check_items("done", done, RestoredDone)
        now = self._check_now(now)
        plans = [self._check_restored_receive(r) for r in recvs]
        if len({r.device_id for r in recvs}) != len(recvs):
            raise ValueError("mỗi thiết bị có tối đa một lượt nhận khôi phục")
        memos: list[tuple[float, str, Direction, str, RestoredTombstone | RestoredDone]] = []
        for d in dones:
            self._check_peer_id(d.device_id)
            if not isinstance(d.offer, Offer):
                raise ValueError("offer phải là Offer")
            age = _check_age("age", d.age)
            if age < REMEMBER_TTL:
                memos.append((age, d.device_id, Direction.RECEIVE, d.offer.transfer_id, d))
        for s in stones:
            self._check_peer_id(s.device_id)
            if not isinstance(s.direction, Direction):
                raise ValueError("direction phải là Direction")
            try:
                validate_transfer_id(s.transfer_id)
                Cancel(s.transfer_id, s.reason)  # cùng luật `reason` như trên dây
            except MessageError as e:
                raise ValueError(f"bia mộ sai: {e}") from None
            if type(s.unsent) is not bool:
                raise ValueError("unsent phải là bool")
            age = _check_age("age", s.age)
            if age < REMEMBER_TTL:
                memos.append((age, s.device_id, s.direction, s.transfer_id, s))
        done_keys = {(m[1], m[3]) for m in memos if isinstance(m[4], RestoredDone)}
        for r in recvs:
            if (r.device_id, r.offer.transfer_id) in done_keys:
                raise ValueError("lượt nhận khôi phục trùng khóa một lượt đã xong")
        self._accept_now(now)
        memos.sort(key=lambda m: -m[0])  # ổn định: cùng tuổi giữ thứ tự đưa vào
        for age, device_id, direction, transfer_id, item in memos:
            memo: _Memo
            if isinstance(item, RestoredDone):
                digest = _manifest_digest(item.offer)
                memo = _DoneMemo(len(item.offer.files), digest, now - age, self._order())
            else:
                memo = _Tombstone(item.reason, item.unsent, now - age, self._order())
            self._peer(device_id).memory.put(direction, transfer_id, memo)
        for r, (n, have_count, have_bytes, age) in zip(recvs, plans, strict=True):
            peer = self._peer(r.device_id)
            transfer_id = r.offer.transfer_id
            if isinstance(peer.memory.get(Direction.RECEIVE, transfer_id, now), _Tombstone):
                self._emit(RemoveTemp(r.device_id, transfer_id))
                continue
            offer = r.offer
            t = _Recv(
                key=TransferKey(r.device_id, Direction.RECEIVE, transfer_id),
                offer=offer,
                names=tuple(dedupe_offer_names([entry.name for entry in offer.files])),
                total_size=sum(entry.size for entry in offer.files),
                phase=_Phase.RUNNING,
                owns_temp=True,
                created=True,
                expire_restored=age >= RECONNECT_GRACE,
                file_index=r.file_index,
                verified_bytes=sum(entry.size for entry in offer.files[: r.file_index]),
                n_f=n,
                size_f=offer.files[r.file_index].size,
                bits=_copy_bitfield(r.bits),
                # `bytearray` thì giữ chính nó (app trao quyền sở hữu, không chép file 4 TiB = 128 MiB).
                leaves=r.leaves if isinstance(r.leaves, bytearray) else bytearray(r.leaves),
                have_count=have_count,
                have_bytes=have_bytes,
                hw=r.part_blocks - 1,
            )
            self._add_transfer(peer, t)
            peer.running = t
            peer.offline_since = self._offline_since(now, age)
        return self._finish()

    def suspend_receiving(self, now: float) -> list[TransferAction]:
        """Tạm dừng mọi lượt nhận đang chạy (đóng node có trật tự), không hủy.

        Mỗi lượt: `CloseData` các kết nối dữ liệu của nó, `SyncPart` các khối đã ghi mà chưa vào
        lô (để `MARK` của chúng bền), `SuspendTemp`, rồi `TransferEnded(outcome=SUSPENDED)`.
        Không `cancel`, không `RemoveTemp`, không bia mộ, không xét `offer` đang xếp hàng (bên gọi
        hủy chúng sau đó). Từ đó `offer`, `complete`, `cancel` của lượt đó → `[]`, `data_open`
        của nó → chỉ `CloseData`, và `send` không dùng lại được `transfer_id` của nó với thiết bị đó.
        Engine thôi nhận file (`receiving` = False): `offer` mới tới sau đó → `reject{not_receiving}`.
        """
        now = self._check_now(now)
        self._accept_now(now)
        self._receiving = False
        for t in list(self._transfers.values()):
            if isinstance(t, _Recv) and t.phase is _Phase.RUNNING:
                self._suspended.add(t.key)
                self._end(t, Outcome.SUSPENDED, advance=False)
        return self._finish()

    # ---- Kết nối điều khiển --------------------------------------------------------------

    def control_up(self, device_id: str, control_id: int, client: bool, now: float) -> list[TransferAction]:
        """Có kết nối điều khiển `control_id` (đầu tiên hay thay thế): đồng bộ lại (protocol §6.3).

        `client`: máy này đã mở kết nối đó (kết nối dữ liệu đi theo chiều này, protocol §4.1).
        Trước khi đồng bộ lại, lượt khôi phục có tuổi ≥ `RECONNECT_GRACE` của thiết bị này hết hạn
        như ở `tick` (Q3 không phụ thuộc thứ tự gọi), nên `cancel{expired}` của nó đi ngay sau đó.
        Lượt nhận chưa `temp_created` không được gửi `accept`/`resume`.
        """
        validate_device_id(device_id)
        _check_id("control_id", control_id)
        _check_bool("client", client)
        now = self._check_now(now)
        self._accept_now(now)
        if device_id == self._own_id:
            return []
        peer = self._peers.get(device_id)
        if peer is not None and peer.control is not None and peer.control[0] == control_id:
            return []
        if peer is None:
            peer = self._peers[device_id] = _Peer(device_id)
        for t in list(peer.transfers.values()):
            if isinstance(t, _Recv) and t.expire_restored:
                self._expire(t, now)
        self._drop_data(peer)
        peer.control = (control_id, client)
        peer.max_seq = 0
        peer.next_seq = 1
        for t in peer.transfers.values():
            if isinstance(t, _Send):
                t.latest = None
            else:
                t.sent_resume = False
                t.last_resume = None
        peer.offline_since = None
        peer.open_failures = 0
        peer.unreachable_reported = False
        for transfer_id, reason in peer.memory.take_unsent(now):
            self._send(peer, Cancel(transfer_id, reason))
            self._tombstones_changed = True  # cờ `unsent` đã đổi
        sends = [t for t in peer.transfers.values() if isinstance(t, _Send)]
        for s in sends:
            self._send(peer, s.offer)
        for s in sends:
            for index in sorted(s.states):
                state = s.states[index]
                if state.root is not None and not s.verified[index]:
                    self._send(peer, Complete(s.key.transfer_id, index, state.root.hex()))
        running = peer.running
        if running is not None and running.created:
            self._send(peer, Accept(running.key.transfer_id))
            self._request_resume(peer, running, now)
        return self._finish()

    def control_lost(self, device_id: str, control_id: int, now: float) -> list[TransferAction]:
        """Kết nối điều khiển `control_id` đã mất; là kết nối hiện tại thì chờ nối lại (protocol §6.2)."""
        validate_device_id(device_id)
        _check_id("control_id", control_id)
        now = self._check_now(now)
        self._accept_now(now)
        peer = self._current_peer(device_id, control_id)
        if peer is None:
            return []
        peer.control = None
        self._drop_data(peer)
        running = peer.running
        if running is not None and running.unbatched:
            self._push_batch(peer, running)
        if peer.transfers:
            peer.offline_since = now
        return self._finish()

    def message(
        self, device_id: str, control_id: int, msg: TransferMessage, now: float
    ) -> list[TransferAction]:
        """Message truyền file (đã qua `parse_message`) tới trên kết nối điều khiển `control_id`."""
        validate_device_id(device_id)
        _check_id("control_id", control_id)
        if not isinstance(msg, _TRANSFER_MESSAGE_TYPES):
            raise TypeError(f"không phải message truyền file: {type(msg).__name__}")
        now = self._check_now(now)
        self._accept_now(now)
        peer = self._current_peer(device_id, control_id)
        if peer is None:
            return []
        if (
            isinstance(msg, Offer | Complete | Cancel)
            and TransferKey(device_id, Direction.RECEIVE, msg.transfer_id) in self._suspended
        ):
            return []  # S1: lượt nhận đã tạm dừng, máy gửi phải thấy mất kết nối rồi nối lại
        if isinstance(msg, Offer):
            self._on_offer(peer, msg, now)
        elif isinstance(msg, Complete):
            self._on_complete(peer, msg, now)
        elif isinstance(msg, Accept):
            self._on_accept(peer, msg)
        elif isinstance(msg, Reject):
            self._on_reject(peer, msg)
        elif isinstance(msg, Resume):
            self._on_resume(peer, msg, now)
        elif isinstance(msg, Verified):
            self._on_verified(peer, msg, now)
        else:
            self._on_cancel(peer, msg, now)
        return self._finish()

    # ---- Người dùng / app ----------------------------------------------------------------

    def send(
        self, device_id: str, transfer_id: str, files: Sequence[FileEntry], now: float
    ) -> list[TransferAction]:
        """Tạo lượt gửi `files` tới `device_id` với mã `transfer_id` (do bên gọi sinh, UUID4).

        Gửi tới chính máy này → ValueError; `files` sai → MessageError; `transfer_id` đã có
        trong bảng của thiết bị đó, ở bất kỳ chiều nào → TransferIdInUse.
        """
        validate_device_id(device_id)
        validate_transfer_id(transfer_id)
        if isinstance(files, str | bytes) or not isinstance(files, Sequence):
            raise MessageError("files phải là một dãy FileEntry")
        offer = Offer(transfer_id, BLOCK_SIZE, tuple(files))
        now = self._check_now(now)
        if device_id == self._own_id:
            raise ValueError("không gửi file cho chính máy này")
        peer = self._peers.get(device_id)
        if peer is not None and (
            (Direction.SEND, transfer_id) in peer.transfers
            or (Direction.RECEIVE, transfer_id) in peer.transfers
            or peer.memory.knows(transfer_id, now)
            or TransferKey(device_id, Direction.RECEIVE, transfer_id) in self._suspended
        ):
            raise TransferIdInUse(f"transfer_id {transfer_id} đã được dùng với thiết bị này")
        self._accept_now(now)
        if peer is None:
            peer = self._peers[device_id] = _Peer(device_id)
        t = _Send(
            key=TransferKey(device_id, Direction.SEND, transfer_id),
            offer=offer,
            names=tuple(entry.name for entry in offer.files),
            total_size=sum(entry.size for entry in offer.files),
            verified=bytearray(len(offer.files)),
        )
        self._add_transfer(peer, t)
        if peer.control is not None:
            self._send(peer, offer)
        elif peer.offline_since is None:
            peer.offline_since = now
        return self._finish()

    def space_checked(
        self,
        device_id: str,
        transfer_id: str,
        free_bytes: int | None,
        max_file_size: int | None,
        now: float,
        *,
        check_id: int | None = None,
    ) -> list[TransferAction]:
        """Kết quả `CheckSpace` (`free_bytes` thô; None: không biết).

        `check_id` là `CheckSpace.check_id` của lần kiểm; khác lần kiểm mới nhất của lượt (đã có
        `recheck_space` sau đó) → `[]`. None coi như khớp. Lượt đang hỏi người dùng mà đang kiểm
        lại: thiếu chỗ hay vượt trần → từ chối như lần kiểm đầu; đủ → thôi kiểm lại, không hỏi lại,
        và nếu người dùng đã bấm Nhận trong lúc chờ thì chấp nhận ngay như `decide(True)`.
        """
        validate_device_id(device_id)
        validate_transfer_id(transfer_id)
        free_bytes = _check_optional_size("free_bytes", free_bytes)
        max_file_size = _check_optional_size("max_file_size", max_file_size)
        check_id = _check_optional_size("check_id", check_id)
        now = self._check_now(now)
        self._accept_now(now)
        found = self._lookup(device_id, Direction.RECEIVE, transfer_id)
        if found is None:
            return []
        peer, t = found
        if not isinstance(t, _Recv) or not (
            t.phase is _Phase.CHECKING or (t.phase is _Phase.ASKING and t.rechecking)
        ):
            return []
        if check_id is not None and check_id != t.check_id:
            return []  # kết quả của lần kiểm cũ (thư mục nhận trước `recheck_space`)
        promised = self.promised_bytes()
        if t.phase is _Phase.ASKING:
            promised -= t.total_size  # lượt đang hỏi đã tính chính nó vào phần đã hứa
        free = None if free_bytes is None else max(0, free_bytes - promised)
        rej = check_offer(t.offer, free_bytes=free, max_file_size=max_file_size)
        if rej is not None:
            self._reject(peer, t, rej, now)
        elif t.phase is _Phase.CHECKING:
            t.phase = _Phase.ASKING
            self._emit(AskUser(device_id, transfer_id, t.offer, t.names))
        else:
            t.rechecking = False
            if t.accept_pending:
                t.accept_pending = False
                self._accept_offer(peer, t, now)
        return self._finish()

    def recheck_space(self, now: float) -> list[TransferAction]:
        """Thư mục nhận vừa đổi: kiểm lại chỗ trống cho mọi `offer` đang kiểm hay đang hỏi.

        Lượt đang kiểm: `CheckSpace` mới (kết quả của lần cũ bị bỏ). Lượt đang hỏi người dùng:
        `CheckSpace` mới, không `AskUser` lại; hộp hỏi giữ nguyên, Nhận trong lúc chờ kết quả chỉ
        được ghi lại (`decide`). Lượt đang xếp hàng được kiểm khi tới lượt. Bên gọi chỉ đổi thư mục
        khi không còn lượt nhận đã chấp nhận (`has_accepted_receives`), nên phần đã hứa không đổi.
        """
        now = self._check_now(now)
        self._accept_now(now)
        for t in self._transfers.values():
            if not isinstance(t, _Recv):
                continue
            if t.phase is _Phase.CHECKING:
                self._emit_check_space(t)
            elif t.phase is _Phase.ASKING:
                t.rechecking = True
                self._emit_check_space(t)
        return self._finish()

    def decide(self, device_id: str, transfer_id: str, accept: bool, now: float) -> list[TransferAction]:
        """Người dùng (hoặc `--yes`) trả lời `AskUser`.

        Đang kiểm lại chỗ trống (`recheck_space`): nhận → chỉ ghi lại, chấp nhận khi kết quả đủ chỗ
        (`space_checked`), bỏ nếu kết quả là từ chối; không nhận → từ chối ngay.
        """
        validate_device_id(device_id)
        validate_transfer_id(transfer_id)
        _check_bool("accept", accept)
        now = self._check_now(now)
        self._accept_now(now)
        found = self._lookup(device_id, Direction.RECEIVE, transfer_id)
        if found is None:
            return []
        peer, t = found
        if not isinstance(t, _Recv) or t.phase is not _Phase.ASKING:
            return []
        if not accept:
            self._reject(peer, t, Reject(transfer_id, RejectReason.USER), now)
        elif t.rechecking:
            t.accept_pending = True
        else:
            self._accept_offer(peer, t, now)
        return self._finish()

    def temp_created(self, device_id: str, transfer_id: str, now: float) -> list[TransferAction]:
        """`CreateTemp` của lượt nhận đã xong: thư mục tạm và `transfer.json` đã bền.

        Có kết nối điều khiển → gửi `accept` rồi `resume` đang giữ; không có → chờ `control_up`.
        Lượt lạ, đã kết thúc hay đã `temp_created` → `[]`.
        """
        validate_device_id(device_id)
        validate_transfer_id(transfer_id)
        now = self._check_now(now)
        self._accept_now(now)
        found = self._running_recv(device_id, transfer_id)
        if found is None or found[1].created:
            return []
        peer, t = found
        t.created = True
        if peer.control is not None:
            self._send(peer, Accept(transfer_id))
            self._request_resume(peer, t, now)
        return self._finish()

    def cancel(self, key: TransferKey, now: float) -> list[TransferAction]:
        """Người dùng hủy lượt `key` (ở trạng thái nào cũng được)."""
        if not isinstance(key, TransferKey):
            raise TypeError("key phải là TransferKey")
        validate_device_id(key.device_id)
        if not isinstance(key.direction, Direction):
            raise ValueError("direction phải là Direction")
        validate_transfer_id(key.transfer_id)
        now = self._check_now(now)
        self._accept_now(now)
        t = self._transfers.get(key)
        if t is None:
            return []
        peer = self._peers[key.device_id]
        if isinstance(t, _Recv) and t.phase is not _Phase.RUNNING:
            self._reject(peer, t, Reject(key.transfer_id, RejectReason.USER), now)
        else:
            self._fail(t, CancelReason.USER, None, now)
        return self._finish()

    # ---- Kết nối dữ liệu -----------------------------------------------------------------

    def incoming_data(self, device_id: str, data_id: int, msg: DataOpen, now: float) -> list[TransferAction]:
        """Máy kia mở kết nối dữ liệu `data_id` tới máy này với `data_open` = `msg` (protocol §4.1)."""
        validate_device_id(device_id)
        _check_id("data_id", data_id)
        if not isinstance(msg, DataOpen):
            raise TypeError("msg phải là DataOpen")
        now = self._check_now(now)
        self._check_new_data_id(data_id)
        self._accept_now(now)
        if device_id == self._own_id:
            return []
        peer = self._peers.get(device_id)
        if peer is None or peer.control is None or peer.control[1]:
            # Không có kết nối điều khiển, hoặc sai chiều: chỉ đóng.
            self._emit(CloseData(device_id, data_id))
            return self._finish()
        transfer_id = msg.transfer_id
        t = self._find_any(peer, transfer_id)
        if t is None and TransferKey(device_id, Direction.RECEIVE, transfer_id) in self._suspended:
            self._emit(CloseData(device_id, data_id))  # S1: lượt đã tạm dừng, không `cancel`
        elif t is None:
            tombstone = peer.memory.tombstone(transfer_id, now)
            reason = tombstone.reason if tombstone is not None else CancelReason.UNKNOWN_TRANSFER
            self._send(peer, Cancel(transfer_id, reason))
            self._emit(CloseData(device_id, data_id))
        elif isinstance(t, _Send):
            self._incoming_send(peer, t, data_id, msg, now)
        elif self._recv_matches(t, msg):
            self._attach_receiving(peer, t, data_id, msg)
        else:
            self._emit(CloseData(device_id, data_id))
        return self._finish()

    def outgoing_data(
        self, device_id: str, control_id: int, data_id: int, msg: DataOpen, now: float
    ) -> list[TransferAction]:
        """`OpenData(device_id, control_id, msg)` đã mở được kết nối `data_id`."""
        validate_device_id(device_id)
        _check_id("control_id", control_id)
        _check_id("data_id", data_id)
        if not isinstance(msg, DataOpen):
            raise TypeError("msg phải là DataOpen")
        now = self._check_now(now)
        self._check_new_data_id(data_id)
        self._accept_now(now)
        if device_id == self._own_id:
            return []
        peer = self._peers.get(device_id)
        t = self._outgoing_target(peer, control_id, msg)
        if peer is None or t is None:
            self._emit(CloseData(device_id, data_id))
            return self._finish()
        if isinstance(t, _Send):
            latest = t.latest
            assert latest is not None
            if t.conn is not None:
                self._close_conn(t.conn)
            self._attach_serving(peer, t, data_id, latest)
        else:
            self._attach_receiving(peer, t, data_id, msg)
        peer.open_failures = 0
        peer.unreachable_reported = False
        return self._finish()

    def outgoing_data_failed(
        self, device_id: str, control_id: int, msg: DataOpen, now: float
    ) -> list[TransferAction]:
        """`OpenData(device_id, control_id, msg)` thất bại (kể cả hết hạn mở)."""
        validate_device_id(device_id)
        _check_id("control_id", control_id)
        if not isinstance(msg, DataOpen):
            raise TypeError("msg phải là DataOpen")
        now = self._check_now(now)
        self._accept_now(now)
        if device_id == self._own_id:
            return []
        peer = self._peers.get(device_id)
        t = self._outgoing_target(peer, control_id, msg)
        if peer is None or t is None:
            return []
        peer.open_failures += 1
        if peer.open_failures >= DATA_FAIL_REPORT_AFTER and not peer.unreachable_reported:
            peer.unreachable_reported = True
            self._report(DataUnreachable(device_id))
        t.idle_rounds += 1
        at = now + _retry_delay(t.idle_rounds)
        if isinstance(t, _Send):
            t.retry_at = at
            t.retry_msg = msg
        else:
            t.resume_at = at
        return self._finish()

    def data_closed(self, device_id: str, data_id: int, finished: bool, now: float) -> list[TransferAction]:
        """Kết nối dữ liệu `data_id` đã đóng. `finished` (bên gửi): đã ghi xong mọi khung được yêu cầu."""
        validate_device_id(device_id)
        _check_id("data_id", data_id)
        _check_bool("finished", finished)
        now = self._check_now(now)
        self._accept_now(now)
        conn = self._conns.get(data_id)
        if conn is None or conn.device_id != device_id:
            return []
        peer = self._peers[device_id]
        self._forget_conn(conn)
        if conn.kind is _ConnKind.PENDING:
            return self._finish()
        t = self._transfers[conn.key]
        if isinstance(t, _Send):
            if finished:
                t.idle_rounds = 0
            elif (
                peer.control is not None and peer.control[1] and self._latest_is(t, conn.file_index, conn.seq)
            ):
                t.idle_rounds += 1
                t.retry_at = now + _retry_delay(t.idle_rounds)
                t.retry_msg = DataOpen(t.key.transfer_id, conn.file_index, conn.seq)
        else:
            t.idle_rounds = 0 if conn.progressed else t.idle_rounds + 1
            if t.have_count + len(t.pending) < t.n_f:
                if t.idle_rounds == 0:
                    self._request_resume(peer, t, now)
                else:
                    t.resume_at = now + _retry_delay(t.idle_rounds)
        return self._finish()

    def block_read(
        self, device_id: str, data_id: int, index: int, digest: bytes, now: float
    ) -> list[TransferAction]:
        """Bên gửi đã đọc và băm khối `index` để ghi lên kết nối `data_id` (chưa ghi)."""
        validate_device_id(device_id)
        _check_id("data_id", data_id)
        _check_range("index", index, MAX_BLOCKS - 1)
        _check_digest("digest", digest)
        now = self._check_now(now)
        conn = self._conns.get(data_id)
        if conn is None or conn.device_id != device_id or conn.kind is not _ConnKind.SERVING:
            self._accept_now(now)
            self._emit(CloseData(device_id, data_id))
            return self._finish()
        t = self._transfers[conn.key]
        assert isinstance(t, _Send)
        file_index = conn.file_index
        size = t.offer.files[file_index].size
        if index >= block_count(size):
            raise ValueError(f"index {index} ngoài số khối của file {file_index}")
        self._accept_now(now)
        state = t.states.get(file_index)
        if state is None:
            self._close_conn(conn)
            return self._finish()
        start = index * DIGEST_SIZE
        if index in state.sent:
            if state.leaves[start : start + DIGEST_SIZE] != digest:
                self._fail(t, CancelReason.SOURCE_CHANGED, None, now, file_index=file_index)
            return self._finish()
        state.leaves[start : start + DIGEST_SIZE] = digest
        state.sent.set(index)
        state.sent_count += 1
        state.sent_bytes += _block_len(size, index)
        if state.sent_count == state.n and state.root is None and not state.checking:
            state.checking = True
            self._emit(CheckSource(device_id, t.key.transfer_id, file_index, state.leaves))
        return self._finish()

    def block_received(
        self, device_id: str, data_id: int, index: int, digest: bytes, now: float
    ) -> list[TransferAction]:
        """Bên nhận đã nhận khối `index` trên `data_id`, payload khớp `digest` (chưa ghi)."""
        validate_device_id(device_id)
        _check_id("data_id", data_id)
        _check_range("index", index, MAX_BLOCKS - 1)
        _check_digest("digest", digest)
        now = self._check_now(now)
        self._accept_now(now)
        conn = self._receiving_conn(device_id, data_id)
        if conn is None:
            self._emit(CloseData(device_id, data_id))
            return self._finish()
        t = self._transfers[conn.key]
        assert isinstance(t, _Recv)
        peer = self._peers[device_id]
        if index >= t.n_f or index <= conn.cursor:
            self._bad_block(peer, t, now)
            return self._finish()
        if index in t.bits or index in t.pending:
            conn.cursor = index  # khối trùng: bỏ qua, không đổi bộ đếm khối sai
            return self._finish()
        if index > t.hw + 1:
            self._bad_block(peer, t, now)
            return self._finish()
        t.bad_count = 0
        start = index * DIGEST_SIZE
        t.leaves[start : start + DIGEST_SIZE] = digest
        self._emit(WriteBlock(device_id, t.key.transfer_id, t.file_index, index))
        t.pending.add(index)
        t.pending_bytes += _block_len(t.size_f, index)
        t.unbatched.append((index, digest))
        t.hw = max(t.hw, index)
        conn.cursor = index
        conn.progressed = True
        if len(t.unbatched) >= SYNC_EVERY or t.have_count + len(t.pending) == t.n_f:
            self._push_batch(peer, t)
        return self._finish()

    def block_bad(self, device_id: str, data_id: int, now: float) -> list[TransferAction]:
        """Bên nhận gặp khối sai trên `data_id` (header sai hay hash sai)."""
        validate_device_id(device_id)
        _check_id("data_id", data_id)
        now = self._check_now(now)
        self._accept_now(now)
        conn = self._receiving_conn(device_id, data_id)
        if conn is None:
            self._emit(CloseData(device_id, data_id))
            return self._finish()
        t = self._transfers[conn.key]
        assert isinstance(t, _Recv)
        self._bad_block(self._peers[device_id], t, now)
        return self._finish()

    # ---- Đĩa / file nguồn ----------------------------------------------------------------

    def synced(
        self, device_id: str, transfer_id: str, file_index: int, token: int, now: float
    ) -> list[TransferAction]:
        """`SyncPart` có `token` đã `fsync` xong: bật bit các khối của lô."""
        validate_device_id(device_id)
        validate_transfer_id(transfer_id)
        _check_range("file_index", file_index, MAX_OFFER_FILES - 1)
        _check_id("token", token)
        now = self._check_now(now)
        self._accept_now(now)
        found = self._running_recv(device_id, transfer_id)
        if found is None:
            return []
        peer, t = found
        if file_index != t.file_index or token not in t.batches:
            return []
        for index, _digest in t.batches.pop(token):
            length = _block_len(t.size_f, index)
            t.bits.set(index)
            t.have_count += 1
            t.have_bytes += length
            t.pending.discard(index)
            t.pending_bytes -= length
        if t.want_resume and not t.batches and peer.control is not None and t.created:
            # `resume` đã được xin (đồng bộ lại, khối sai…) nhưng phải chờ `fsync`: gửi ở `synced`
            # cuối cùng, kể cả khi đủ bit (protocol §6.3: bên nhận gửi `resume` trên kết nối mới, để
            # `cancel` của bên gửi bị mất được trả lại). Đủ bit thì không mở kết nối dữ liệu.
            self._send_resume(peer, t, now)
        if t.have_count == t.n_f:
            self._maybe_reread(peer, t)  # chưa có root thì chờ `complete`, không gửi gì thêm (D5)
        return self._finish()

    def reread_done(
        self,
        device_id: str,
        transfer_id: str,
        file_index: int,
        bad: Sequence[int],
        root: bytes | None,
        now: float,
    ) -> list[TransferAction]:
        """Kết quả `Reread`: `bad` = khối có hash trên đĩa khác `leaves`; `root` chỉ khi `bad` rỗng."""
        validate_device_id(device_id)
        validate_transfer_id(transfer_id)
        _check_range("file_index", file_index, MAX_OFFER_FILES - 1)
        bad_blocks = _check_bad(bad)
        if root is None:
            if not bad_blocks:
                raise ValueError("bad rỗng thì phải có root")
        else:
            _check_digest("root", root)
            if bad_blocks:
                raise ValueError("bad khác rỗng thì root phải là None")
        now = self._check_now(now)
        found = self._running_recv(device_id, transfer_id)
        if found is None or file_index != found[1].file_index or not found[1].rereading:
            self._accept_now(now)
            return []
        peer, t = found
        if bad_blocks and bad_blocks[-1] >= t.n_f:
            raise ValueError(f"bad có chỉ số ngoài số khối của file {file_index}")
        self._accept_now(now)
        t.rereading = False
        if bad_blocks:
            cleared: list[int] = []
            for index in bad_blocks:
                if index in t.bits:
                    t.bits.clear(index)
                    t.have_count -= 1
                    t.have_bytes -= _block_len(t.size_f, index)
                    cleared.append(index)
            if cleared:
                self._emit(ClearBlocks(device_id, transfer_id, file_index, tuple(cleared)))
        elif root != t.root:
            t.bits = Bitfield(t.n_f)
            t.have_count = 0
            t.have_bytes = 0
            self._emit(ClearBlocks(device_id, transfer_id, file_index, None))
        else:
            t.finalizing = True
            entry = t.offer.files[file_index]
            self._emit(Finalize(device_id, transfer_id, file_index, t.names[file_index], entry.mtime))
            return self._finish()
        t.verify_failures += 1
        if t.verify_failures > MAX_VERIFY_FAILURES:
            self._fail(t, CancelReason.ERROR, FailureDetail.VERIFY_FAILED, now, file_index=file_index)
        else:
            self._request_resume(peer, t, now)
        return self._finish()

    def finalized(
        self, device_id: str, transfer_id: str, file_index: int, name: str, now: float
    ) -> list[TransferAction]:
        """`Finalize` xong: file đã mang tên thật `name` (có thể đã đánh số)."""
        validate_device_id(device_id)
        validate_transfer_id(transfer_id)
        _check_range("file_index", file_index, MAX_OFFER_FILES - 1)
        if not isinstance(name, str):
            raise TypeError("name phải là chuỗi")
        if not name:
            raise ValueError("name không được rỗng")
        now = self._check_now(now)
        self._accept_now(now)
        found = self._running_recv(device_id, transfer_id)
        if found is None or file_index != found[1].file_index or not found[1].finalizing:
            return []
        peer, t = found
        t.finalizing = False
        if peer.control is not None:
            self._send(peer, Verified(transfer_id, file_index))
        self._report(FileVerified(t.key, file_index, name))
        t.verified_bytes += t.size_f
        n = len(t.offer.files)
        if file_index + 1 < n:
            self._start_file(peer, t, file_index + 1, now)
            return self._finish()
        t.file_index = n
        t.have_count = t.have_bytes = 0
        self._end(t, Outcome.DONE)
        self._remember(
            peer,
            Direction.RECEIVE,
            transfer_id,
            _DoneMemo(n, _manifest_digest(t.offer), now, self._order()),
        )
        return self._finish()

    def storage_failed(
        self,
        device_id: str,
        transfer_id: str,
        op: DiskOp,
        now: float,
        *,
        detail: FailureDetail | None = None,
    ) -> list[TransferAction]:
        """Thao tác đĩa `op` của lượt nhận bị lỗi: dừng lượt (`cancel{error}`).

        `detail` là nguyên nhân ghi vào `TransferEnded.detail`: None (= `DISK`), `DISK`, hoặc
        (chỉ với `op` là `CREATE_TEMP`) `TEMP_EXISTS` (thư mục tạm của lượt đã có sẵn) hay
        `RECEIVE_DIR_MISSING` (thư mục nhận đã mất, không tạo lại được). Giá trị khác →
        ValueError. Trên dây vẫn là `cancel{error}`.
        """
        validate_device_id(device_id)
        validate_transfer_id(transfer_id)
        if not isinstance(op, DiskOp):
            raise ValueError("op phải là DiskOp")
        if detail is None:
            detail = FailureDetail.DISK
        elif isinstance(detail, FailureDetail) and detail in _CREATE_TEMP_DETAILS:  # chuỗi thường không lọt
            if op is not DiskOp.CREATE_TEMP:
                raise ValueError(f"detail {detail.name} chỉ đi với op CREATE_TEMP")
        elif detail is not FailureDetail.DISK:
            raise ValueError("detail phải là None, FailureDetail.DISK, TEMP_EXISTS hoặc RECEIVE_DIR_MISSING")
        now = self._check_now(now)
        self._accept_now(now)
        found = self._running_recv(device_id, transfer_id)
        if found is None:
            return []
        t = found[1]
        if op is DiskOp.CREATE_TEMP:
            t.owns_temp = False  # không tạo được thì không phải của lượt này: không xóa
        self._fail(t, CancelReason.ERROR, detail, now, file_index=t.file_index)
        return self._finish()

    def source_checked(
        self,
        device_id: str,
        transfer_id: str,
        file_index: int,
        size: int,
        mtime: int,
        root: bytes,
        now: float,
    ) -> list[TransferAction]:
        """Kết quả `CheckSource`: `size`, `mtime` (ms) của file nguồn và Merkle root."""
        validate_device_id(device_id)
        validate_transfer_id(transfer_id)
        _check_range("file_index", file_index, MAX_OFFER_FILES - 1)
        _check_range("size", size, MAX_FILE_SIZE)
        _check_range("mtime", mtime, MAX_SAFE_INTEGER)
        _check_digest("root", root)
        now = self._check_now(now)
        self._accept_now(now)
        found = self._lookup(device_id, Direction.SEND, transfer_id)
        if found is None:
            return []
        peer, t = found
        assert isinstance(t, _Send)
        state = t.states.get(file_index)
        if state is None or not state.checking:
            return []
        state.checking = False
        entry = t.offer.files[file_index]
        if size != entry.size or mtime != entry.mtime:
            self._fail(t, CancelReason.SOURCE_CHANGED, None, now, file_index=file_index)
            return self._finish()
        state.root = root
        if peer.control is not None:
            self._send(peer, Complete(transfer_id, file_index, root.hex()))
        return self._finish()

    def source_failed(
        self, device_id: str, transfer_id: str, file_index: int, changed: bool, now: float
    ) -> list[TransferAction]:
        """Đọc file nguồn lỗi (`changed=False`) hay file nguồn đã đổi (`changed=True`)."""
        validate_device_id(device_id)
        validate_transfer_id(transfer_id)
        _check_range("file_index", file_index, MAX_OFFER_FILES - 1)
        _check_bool("changed", changed)
        now = self._check_now(now)
        self._accept_now(now)
        found = self._lookup(device_id, Direction.SEND, transfer_id)
        if found is None:
            return []
        t = found[1]
        if changed:
            self._fail(t, CancelReason.SOURCE_CHANGED, None, now, file_index=file_index)
        else:
            self._fail(t, CancelReason.ERROR, FailureDetail.SOURCE_READ, now, file_index=file_index)
        return self._finish()

    # ---- Hẹn giờ -------------------------------------------------------------------------

    def tick(self, now: float) -> list[TransferAction]:
        """Xử lý mọi hạn ≤ `now`, theo `device_id` tăng dần rồi theo thứ tự tạo."""
        now = self._check_now(now)
        self._accept_now(now)
        for device_id in sorted(self._peers):
            peer = self._peers[device_id]
            for conn in list(peer.pending):
                if conn.deadline <= now:
                    self._close_conn(conn)
            for t in list(peer.transfers.values()):
                if isinstance(t, _Send):
                    if t.retry_at is not None and t.retry_at <= now:
                        msg = t.retry_msg
                        t.retry_at = None
                        t.retry_msg = None
                        if (
                            msg is not None
                            and peer.control is not None
                            and peer.control[1]
                            and t.conn is None
                            and self._latest_is(t, msg.file_index, msg.resume_seq)
                        ):
                            self._emit(OpenData(device_id, peer.control[0], msg))
                    continue
                if t.open_wait_at is not None and t.open_wait_at <= now:
                    # Máy này là server mà không có `data_open` khớp `resume` vừa gửi: hẹn `resume`
                    # mới theo lịch §6.2 (như `outgoing_data_failed`), không tăng `open_failures`.
                    t.open_wait_at = None
                    t.idle_rounds += 1
                    t.resume_at = now + _retry_delay(t.idle_rounds)
                if t.resume_at is not None and t.resume_at <= now:
                    t.resume_at = None
                    if t.phase is _Phase.RUNNING:
                        self._request_resume(peer, t, now)
            if (
                peer.control is None
                and peer.offline_since is not None
                and peer.transfers
                and now >= peer.offline_since + RECONNECT_GRACE
            ):
                for t in list(peer.transfers.values()):
                    self._expire(t, now)
            peer.memory.prune(now)
        return self._finish()

    # ---- Nội bộ: tham số, khung lời gọi ----------------------------------------------------

    def _check_now(self, now: object) -> float:
        if isinstance(now, bool) or not isinstance(now, int | float):
            raise TypeError("now phải là số giây (đồng hồ monotonic)")
        value = _finite_float(now)
        if value is None:
            raise ValueError("now phải là số hữu hạn")
        if self._last_now is not None and value < self._last_now:
            raise ValueError("now không được giảm")
        return value

    def _check_new_data_id(self, data_id: int) -> None:
        if data_id in self._conns:
            raise ValueError(f"data_id {data_id} đang được theo dõi")

    def _check_peer_id(self, device_id: object) -> str:
        """`device_id` của dữ liệu khôi phục: hợp lệ và không phải máy này (sai → ValueError)."""
        device_id = validate_device_id(device_id)
        if device_id == self._own_id:
            raise ValueError("dữ liệu khôi phục không được nhắc tới chính máy này")
        return device_id

    def _check_restored_receive(self, r: RestoredReceive) -> tuple[int, int, int, float]:
        """Kiểm một `RestoredReceive`; trả `(số khối, số bit bật, số byte các khối đó, tuổi)`."""
        self._check_peer_id(r.device_id)
        if not isinstance(r.offer, Offer):
            raise ValueError("offer phải là Offer")
        files = r.offer.files
        file_index = r.file_index
        if type(file_index) is not int or not 0 <= file_index < len(files):
            raise ValueError(f"file_index phải là số nguyên 0…{len(files) - 1}")
        size = files[file_index].size
        n = block_count(size)
        if not isinstance(r.bits, Bitfield) or len(r.bits) != n:
            raise ValueError(f"bits phải là Bitfield đúng {n} khối")
        if not isinstance(r.leaves, bytes | bytearray) or len(r.leaves) != DIGEST_SIZE * n:
            raise ValueError(f"leaves phải dài đúng {DIGEST_SIZE * n} byte")
        part_blocks = _check_range("part_blocks", r.part_blocks, n)
        raw = r.bits.to_bytes()
        value = int.from_bytes(raw, "big")
        if value & ((1 << (8 * len(raw) - part_blocks)) - 1):  # bit MSB trước: khối ≥ part_blocks ở đuôi
            raise ValueError("bit của khối từ part_blocks trở đi phải tắt")
        have_count = value.bit_count()
        have_bytes = have_count * BLOCK_SIZE
        if n and n - 1 in r.bits:
            have_bytes -= BLOCK_SIZE - _block_len(size, n - 1)
        return n, have_count, have_bytes, _check_age("age", r.age)

    @staticmethod
    def _offline_since(now: float, age: float) -> float:
        """Mốc mất kết nối của lượt khôi phục: `now − age`; tuổi ≥ `RECONNECT_GRACE` thì chắc chắn
        `mốc + RECONNECT_GRACE ≤ now` (làm tròn số thực không được đẩy hạn sang sau `tick` đầu)."""
        grace = RECONNECT_GRACE
        since = now - age
        if age >= grace:
            since = min(since, now - grace)
            while since + grace > now:
                since = math.nextafter(since, -math.inf)
        return since

    def _accept_now(self, now: float) -> None:
        """Mọi kiểm tra đã qua: ghi mốc `now`, bắt đầu gom hành động của lời gọi này."""
        self._last_now = now
        self._actions = []
        self._reports = []
        self._tombstones_changed = False

    def _emit(self, action: TransferAction) -> None:
        self._actions.append(action)

    def _report(self, event: TransferEvent) -> None:
        self._reports.append(Report(event))

    def _send(self, peer: _Peer, msg: TransferMessage) -> None:
        assert peer.control is not None
        self._emit(SendMessage(peer.device_id, peer.control[0], msg))

    def _order(self) -> int:
        order = self._next_order
        self._next_order += 1
        return order

    def _remember(self, peer: _Peer, direction: Direction, transfer_id: str, memo: _Memo) -> None:
        """Ghi vào bảng nhớ; tập bia mộ đổi thì lời gọi này kết thúc bằng `TombstonesChanged`."""
        if peer.memory.put(direction, transfer_id, memo):
            self._tombstones_changed = True

    def _finish(self) -> list[TransferAction]:
        """Kết thúc lời gọi: hành động, rồi `Report`, rồi `StatusChanged` (G5)."""
        statuses: list[TransferAction] = []
        seen_send: set[str] = set()
        for t in self._transfers.values():
            older = False
            if isinstance(t, _Send):
                older = t.key.device_id in seen_send
                seen_send.add(t.key.device_id)
            status = self._status(t, older)
            if status is not t.reported:
                t.reported = status
                statuses.append(Report(StatusChanged(t.key, status)))
        if self._tombstones_changed:
            self._tombstones_changed = False
            self._actions.append(TombstonesChanged())
        result = [*self._actions, *self._reports, *statuses]
        self._actions = []
        self._reports = []
        return result

    # ---- Nội bộ: tra cứu -----------------------------------------------------------------

    def _peer(self, device_id: str) -> _Peer:
        """Trạng thái của thiết bị `device_id`, tạo mới nếu chưa có."""
        peer = self._peers.get(device_id)
        if peer is None:
            peer = self._peers[device_id] = _Peer(device_id)
        return peer

    def _current_peer(self, device_id: str, control_id: int) -> _Peer | None:
        """Thiết bị nếu `control_id` là kết nối điều khiển hiện tại của nó; không thì None."""
        if device_id == self._own_id:
            return None
        peer = self._peers.get(device_id)
        if peer is None or peer.control is None or peer.control[0] != control_id:
            return None
        return peer

    def _lookup(
        self, device_id: str, direction: Direction, transfer_id: str
    ) -> tuple[_Peer, _Transfer] | None:
        if device_id == self._own_id:
            return None
        peer = self._peers.get(device_id)
        if peer is None:
            return None
        t = peer.transfers.get((direction, transfer_id))
        return None if t is None else (peer, t)

    def _running_recv(self, device_id: str, transfer_id: str) -> tuple[_Peer, _Recv] | None:
        found = self._lookup(device_id, Direction.RECEIVE, transfer_id)
        if found is None:
            return None
        peer, t = found
        if not isinstance(t, _Recv) or t.phase is not _Phase.RUNNING:
            return None
        return peer, t

    @staticmethod
    def _find_any(peer: _Peer, transfer_id: str) -> _Transfer | None:
        """Lượt chưa kết thúc mang `transfer_id`, chiều nào cũng được (`cancel`, `data_open`)."""
        t = peer.transfers.get((Direction.SEND, transfer_id))
        return t if t is not None else peer.transfers.get((Direction.RECEIVE, transfer_id))

    def _receiving_conn(self, device_id: str, data_id: int) -> _DataConn | None:
        conn = self._conns.get(data_id)
        if conn is None or conn.device_id != device_id or conn.kind is not _ConnKind.RECEIVING:
            return None
        return conn

    @staticmethod
    def _latest_is(t: _Send, file_index: int, seq: int) -> bool:
        latest = t.latest
        return latest is not None and latest.file_index == file_index and latest.seq == seq

    @staticmethod
    def _recv_matches(t: _Recv, msg: DataOpen) -> bool:
        """`data_open` khớp `resume` gần nhất (không đủ bit) mà máy này đã gửi trên kết nối hiện tại."""
        return (
            t.phase is _Phase.RUNNING
            and t.created  # chưa `temp_created` thì chưa có `resume` nào: `data_open` → `CloseData`
            and msg.file_index == t.file_index
            and t.last_resume == (msg.file_index, msg.resume_seq, False)
        )

    def _outgoing_target(self, peer: _Peer | None, control_id: int, msg: DataOpen) -> _Transfer | None:
        """Lượt mà kết quả `OpenData` thuộc về, nếu nó vẫn khớp `resume` mới nhất; không thì None."""
        if peer is None or peer.control != (control_id, True):
            return None
        t = self._find_any(peer, msg.transfer_id)
        if isinstance(t, _Send):
            latest = t.latest
            if self._latest_is(t, msg.file_index, msg.resume_seq) and latest is not None and not latest.full:
                return t
            return None
        if isinstance(t, _Recv) and self._recv_matches(t, msg):
            return t
        return None

    def _has_older_send(self, t: _Transfer) -> bool:
        if not isinstance(t, _Send):
            return False
        for other in self._peers[t.key.device_id].transfers.values():
            if other is t:
                return False
            if isinstance(other, _Send):
                return True
        return False

    # ---- Nội bộ: trạng thái, báo cáo -----------------------------------------------------

    def _status(self, t: _Transfer, older_send: bool) -> TransferStatus:
        peer = self._peers[t.key.device_id]
        failing = (
            peer.control is not None and peer.control[1] and peer.open_failures >= DATA_FAIL_REPORT_AFTER
        )
        if isinstance(t, _Send):
            if peer.control is None:
                return TransferStatus.RECONNECTING
            if t.accepted:
                return TransferStatus.RECONNECTING if failing else TransferStatus.TRANSFERRING
            return TransferStatus.QUEUED if older_send else TransferStatus.WAITING
        if t.phase is _Phase.QUEUED:
            return TransferStatus.QUEUED
        if t.phase is not _Phase.RUNNING:
            return TransferStatus.WAITING
        if peer.control is None:
            return TransferStatus.RECONNECTING
        if t.rereading or t.finalizing:
            return TransferStatus.VERIFYING
        return TransferStatus.RECONNECTING if failing else TransferStatus.TRANSFERRING

    def _info(self, t: _Transfer, status: TransferStatus) -> TransferInfo:
        unsynced = 0
        if isinstance(t, _Send):
            file_index = t.verified_count
            done = t.verified_bytes + sum(state.sent_bytes for state in t.states.values())
        else:
            file_index = t.file_index
            done = t.verified_bytes + t.have_bytes
            unsynced = t.pending_bytes
        return TransferInfo(t.key, status, t.offer.files, t.names, file_index, done, t.total_size, unsynced)

    def _default_file_index(self, t: _Transfer) -> int | None:
        n = len(t.offer.files)
        if isinstance(t, _Recv):
            return t.file_index if t.phase is _Phase.RUNNING and t.file_index < n else None
        if not t.served:
            return None
        index = t.verified.find(0)
        return None if index < 0 else index

    # ---- Nội bộ: thêm, kết thúc lượt -----------------------------------------------------

    def _add_transfer(self, peer: _Peer, t: _Transfer) -> None:
        peer.transfers[(t.key.direction, t.key.transfer_id)] = t
        self._transfers[t.key] = t

    def _end(
        self,
        t: _Transfer,
        outcome: Outcome,
        *,
        reason: str | None = None,
        by_peer: bool = False,
        detail: FailureDetail | None = None,
        file_index: int | _Default | None = _Default.INDEX,
        reject: Reject | None = None,
        advance: bool = True,
    ) -> None:
        """Gỡ lượt: đóng kết nối dữ liệu, bỏ lịch, `RemoveTemp` nếu sở hữu, `TransferEnded`.

        `SUSPENDED` thay `RemoveTemp` bằng `SyncPart` (khối chưa vào lô) rồi `SuspendTemp`.
        """
        peer = self._peers[t.key.device_id]
        index: int | None
        if isinstance(file_index, _Default):
            index = self._default_file_index(t)
        elif file_index is not None and 0 <= file_index < len(t.offer.files):
            index = file_index
        else:
            index = None
        status = t.reported if t.reported is not None else self._status(t, self._has_older_send(t))
        info = self._info(t, status)
        if t.conn is not None:
            self._close_conn(t.conn)
        for conn in [c for c in peer.pending if c.key == t.key]:
            self._close_conn(conn)
        if isinstance(t, _Send):
            t.retry_at = None
            t.retry_msg = None
        else:
            t.resume_at = None
            t.open_wait_at = None
            if t.owns_temp:
                t.owns_temp = False
                if outcome is Outcome.SUSPENDED:
                    if t.unbatched:
                        self._push_batch(peer, t)  # `MARK` của các khối đã ghi bền trước khi dừng
                    self._emit(SuspendTemp(peer.device_id, t.key.transfer_id))
                else:
                    keep = outcome is Outcome.DONE
                    self._emit(RemoveTemp(peer.device_id, t.key.transfer_id, keep_record=keep))
            if t in peer.offers:
                peer.offers.remove(t)
            if peer.running is t:
                peer.running = None
        del peer.transfers[(t.key.direction, t.key.transfer_id)]
        del self._transfers[t.key]
        self._report(TransferEnded(t.key, outcome, reason, by_peer, detail, index, reject, info))
        if not peer.transfers:
            peer.offline_since = None
        if isinstance(t, _Recv) and advance:
            self._advance_queue(peer)

    def _tombstone(self, peer: _Peer, t: _Transfer, reason: str, unsent: bool, now: float) -> None:
        memo = _Tombstone(reason, unsent, now, self._order())
        self._remember(peer, t.key.direction, t.key.transfer_id, memo)

    def _fail(
        self,
        t: _Transfer,
        reason: str,
        detail: FailureDetail | None,
        now: float,
        *,
        file_index: int | _Default | None = _Default.INDEX,
    ) -> None:
        """Máy này phát hiện lỗi hay người dùng hủy: `cancel` (nếu có kết nối), bia mộ, kết thúc."""
        peer = self._peers[t.key.device_id]
        unsent = peer.control is None
        if not unsent:
            self._send(peer, Cancel(t.key.transfer_id, reason))
        self._tombstone(peer, t, reason, unsent, now)
        self._end(t, Outcome.CANCELLED, reason=reason, detail=detail, file_index=file_index)

    def _peer_cancel(self, t: _Transfer, reason: str, now: float) -> None:
        """Máy kia hủy: không gửi gì, bia mộ mang lý do của nó."""
        self._tombstone(self._peers[t.key.device_id], t, reason, False, now)
        self._end(t, Outcome.CANCELLED, reason=reason, by_peer=True)

    def _expire(self, t: _Transfer, now: float) -> None:
        """Hết hạn chờ nối lại (protocol §6.2): bia mộ `expired`, gửi `cancel` ở lần `control_up` sau."""
        self._tombstone(self._peers[t.key.device_id], t, CancelReason.EXPIRED, True, now)
        self._end(t, Outcome.CANCELLED, reason=CancelReason.EXPIRED, advance=False)

    def _reject(self, peer: _Peer, t: _Recv, rej: Reject, now: float) -> None:
        """Máy này từ chối `offer` đang chờ: gửi (nếu có kết nối), nhớ, kết thúc REJECTED."""
        if peer.control is not None:
            self._send(peer, rej)
        self._remember(peer, Direction.RECEIVE, t.key.transfer_id, _RejectMemo(rej, now, self._order()))
        self._end(t, Outcome.REJECTED, reason=rej.reason, file_index=rej.file_index, reject=rej)

    # ---- Nội bộ: kết nối dữ liệu ---------------------------------------------------------

    def _register(self, conn: _DataConn) -> None:
        self._conns[conn.data_id] = conn

    def _forget_conn(self, conn: _DataConn) -> None:
        """Quên kết nối (không phát `CloseData`): gỡ khỏi bảng, khỏi danh sách chờ hay khỏi lượt."""
        self._conns.pop(conn.data_id, None)
        if conn.kind is _ConnKind.PENDING:
            pending = self._peers[conn.device_id].pending
            if conn in pending:
                pending.remove(conn)
            return
        t = self._transfers.get(conn.key)
        if t is not None and t.conn is conn:
            t.conn = None

    def _close_conn(self, conn: _DataConn) -> None:
        self._forget_conn(conn)
        self._emit(CloseData(conn.device_id, conn.data_id))

    def _drop_data(self, peer: _Peer) -> None:
        """Đóng mọi kết nối dữ liệu của thiết bị và bỏ mọi lịch đã hẹn (đổi hay mất kết nối điều khiển)."""
        for conn in list(peer.pending):
            self._close_conn(conn)
        for t in peer.transfers.values():
            if t.conn is not None:
                self._close_conn(t.conn)
            if isinstance(t, _Send):
                t.retry_at = None
                t.retry_msg = None
            else:
                t.resume_at = None
                t.open_wait_at = None

    def _attach_serving(self, peer: _Peer, t: _Send, data_id: int, latest: _Latest) -> None:
        conn = _DataConn(data_id, peer.device_id, t.key, _ConnKind.SERVING, latest.file_index, latest.seq)
        self._register(conn)
        t.conn = conn
        size = t.offer.files[latest.file_index].size
        self._emit(
            SendBlocks(
                peer.device_id,
                data_id,
                t.key.transfer_id,
                latest.file_index,
                size,
                _copy_bitfield(latest.have),
            )
        )

    def _attach_receiving(self, peer: _Peer, t: _Recv, data_id: int, msg: DataOpen) -> None:
        if t.conn is not None:
            self._close_conn(t.conn)
        conn = _DataConn(data_id, peer.device_id, t.key, _ConnKind.RECEIVING, msg.file_index, msg.resume_seq)
        self._register(conn)
        t.conn = conn
        t.open_wait_at = None  # `data_open` đã tới: hết chờ
        t.resume_at = None  # `data_open` tới muộn sau khi `tick` đã hẹn `resume` mới: hủy hẹn
        self._emit(ReceiveBlocks(peer.device_id, data_id, t.key.transfer_id, t.file_index, t.size_f))

    def _incoming_send(self, peer: _Peer, t: _Send, data_id: int, msg: DataOpen, now: float) -> None:
        """`data_open` tới bên gửi là server (protocol §4.1)."""
        seq = msg.resume_seq
        if msg.file_index >= len(t.offer.files) or seq < peer.max_seq:
            self._emit(CloseData(peer.device_id, data_id))
            return
        if seq == peer.max_seq:
            latest = t.latest
            if self._latest_is(t, msg.file_index, seq) and latest is not None and not latest.full:
                if t.conn is not None:
                    self._close_conn(t.conn)
                self._attach_serving(peer, t, data_id, latest)
            else:
                self._emit(CloseData(peer.device_id, data_id))
            return
        # `data_open` tới trước `resume`: chờ, có trần mỗi thiết bị.
        while len(peer.pending) >= MAX_PENDING_DATA:
            if not peer.pending:
                self._emit(CloseData(peer.device_id, data_id))
                return
            oldest = min(peer.pending, key=lambda c: c.seq)
            if seq <= oldest.seq:
                self._emit(CloseData(peer.device_id, data_id))
                return
            self._close_conn(oldest)
        conn = _DataConn(
            data_id,
            peer.device_id,
            t.key,
            _ConnKind.PENDING,
            msg.file_index,
            seq,
            deadline=now + DATA_OPEN_WAIT,
        )
        self._register(conn)
        peer.pending.append(conn)

    # ---- Nội bộ: bên gửi -----------------------------------------------------------------

    def _on_accept(self, peer: _Peer, msg: Accept) -> None:
        t = peer.transfers.get((Direction.SEND, msg.transfer_id))
        if isinstance(t, _Send):
            t.accepted = True

    def _on_reject(self, peer: _Peer, msg: Reject) -> None:
        t = peer.transfers.get((Direction.SEND, msg.transfer_id))
        if t is None:
            return
        index = msg.file_index
        if index is not None and index >= len(t.offer.files):
            index = None
        self._end(t, Outcome.REJECTED, reason=msg.reason, by_peer=True, file_index=index, reject=msg)

    def _on_cancel(self, peer: _Peer, msg: Cancel, now: float) -> None:
        t = self._find_any(peer, msg.transfer_id)
        if t is not None:
            self._peer_cancel(t, msg.reason, now)

    def _on_verified(self, peer: _Peer, msg: Verified, now: float) -> None:
        t = peer.transfers.get((Direction.SEND, msg.transfer_id))
        if not isinstance(t, _Send):
            return
        n = len(t.offer.files)
        index = msg.file_index
        if index >= n:
            self._fail(t, CancelReason.ERROR, FailureDetail.PROTOCOL, now, file_index=None)
            return
        if t.verified[index]:
            return
        state = t.states.get(index)
        if state is None or state.root is None:
            self._fail(t, CancelReason.ERROR, FailureDetail.PROTOCOL, now, file_index=index)
            return
        if index == n - 1:
            # `verified` của file cuối kéo theo mọi file trước: bên nhận đổi tên theo thứ tự.
            for j in range(n):
                if not t.verified[j]:
                    self._mark_verified(t, j)
        else:
            self._mark_verified(t, index)
        if t.verified_count == n:
            self._end(t, Outcome.DONE)

    def _mark_verified(self, t: _Send, index: int) -> None:
        t.verified[index] = 1
        t.verified_count += 1
        t.verified_bytes += t.offer.files[index].size
        t.states.pop(index, None)
        if t.conn is not None and t.conn.file_index == index:
            self._close_conn(t.conn)
        if t.latest is not None and t.latest.file_index == index:
            t.latest = None
            t.retry_at = None
            t.retry_msg = None
        self._report(FileVerified(t.key, index, t.offer.files[index].name))

    def _on_resume(self, peer: _Peer, msg: Resume, now: float) -> None:
        transfer_id, index, seq = msg.transfer_id, msg.file_index, msg.seq
        memo = peer.memory.get(Direction.SEND, transfer_id, now)
        if isinstance(memo, _Tombstone):
            self._send(peer, Cancel(transfer_id, memo.reason))
            return
        t = peer.transfers.get((Direction.SEND, transfer_id))
        if not isinstance(t, _Send):
            self._send(peer, Cancel(transfer_id, CancelReason.UNKNOWN_TRANSFER))
            return
        if seq <= peer.max_seq:
            return  # `resume` cũ hay trùng
        peer.max_seq = seq
        for conn in [c for c in peer.pending if c.seq < seq]:
            self._close_conn(conn)
        if t.conn is not None:
            self._close_conn(t.conn)  # nó phục vụ một `resume` cũ hơn
        t.retry_at = None
        t.retry_msg = None
        files = t.offer.files
        if index >= len(files):
            self._fail(t, CancelReason.ERROR, FailureDetail.PROTOCOL, now)
            return
        size = files[index].size
        n = block_count(size)
        try:
            have = Bitfield.from_base64(msg.bitfield, n)
        except ValueError:
            self._fail(t, CancelReason.ERROR, FailureDetail.PROTOCOL, now)
            return
        t.accepted = True  # `accept` có thể đã mất (protocol §6.3, cột “Gửi”, luật 4)
        if t.verified[index]:
            # Bên nhận đã khởi động lại: gửi lại file đó với trạng thái mới.
            t.verified[index] = 0
            t.verified_count -= 1
            t.verified_bytes -= size
        state = t.states.get(index)
        if state is None:
            state = _SendFile(n, Bitfield(n), bytearray(DIGEST_SIZE * n))
            t.states[index] = state
            t.served = True
        # O(n) một lần mỗi `resume`, bằng số nguyên lớn (vòng lặp ở C, không lặp từng bit).
        raw = have.to_bytes()
        have_bits = int.from_bytes(raw, "big")
        if have_bits & ~int.from_bytes(state.sent.to_bytes(), "big"):
            # Bên nhận khai có khối mà bên gửi chưa từng gửi.
            self._fail(t, CancelReason.ERROR, FailureDetail.PROTOCOL, now, file_index=index)
            return
        full = have_bits == ((1 << n) - 1) << (8 * len(raw) - n)
        latest = _Latest(index, seq, have, full)
        t.latest = latest
        if full:
            if state.root is not None:
                self._send(peer, Complete(transfer_id, index, state.root.hex()))
            elif state.sent_count == state.n and not state.checking:
                state.checking = True
                self._emit(CheckSource(peer.device_id, transfer_id, index, state.leaves))
            return
        assert peer.control is not None
        control_id, client = peer.control
        if client:
            self._emit(OpenData(peer.device_id, control_id, DataOpen(transfer_id, index, seq)))
            return
        same_seq = [c for c in peer.pending if c.seq == seq]
        chosen: _DataConn | None = None
        for conn in reversed(same_seq):  # kết nối mới nhất thắng
            if conn.key == t.key and conn.file_index == index:
                chosen = conn
                break
        for conn in same_seq:
            if conn is not chosen:
                self._close_conn(conn)
        if chosen is not None:
            self._forget_conn(chosen)
            self._attach_serving(peer, t, chosen.data_id, latest)

    # ---- Nội bộ: bên nhận ----------------------------------------------------------------

    def _on_offer(self, peer: _Peer, msg: Offer, now: float) -> None:
        """`offer` (protocol §6.3, cột “Nhận”, luật 1–4, 8, 9)."""
        transfer_id = msg.transfer_id
        memo = peer.memory.get(Direction.RECEIVE, transfer_id, now)
        if isinstance(memo, _Tombstone):
            self._send(peer, Cancel(transfer_id, memo.reason))
            return
        t = peer.transfers.get((Direction.RECEIVE, transfer_id))
        if isinstance(t, _Recv) and t.offer.files != msg.files:
            self._fail(t, CancelReason.ERROR, FailureDetail.PROTOCOL, now)
            return
        if isinstance(memo, _DoneMemo) and _manifest_digest(msg) != memo.manifest_digest:
            self._fail_done(peer, transfer_id, now)
            return
        if isinstance(memo, _RejectMemo):
            self._send(peer, memo.reject)
            return
        if isinstance(t, _Recv):
            if t.phase is _Phase.RUNNING and t.created:
                self._send(peer, Accept(transfer_id))
                if not t.sent_resume and not t.want_resume and t.resume_at is None:
                    self._request_resume(peer, t, now)
            return  # đang chờ người dùng, đang xếp hàng hay chưa `temp_created`: im lặng
        if isinstance(memo, _DoneMemo):
            self._send(peer, Accept(transfer_id))
            return
        if (Direction.SEND, transfer_id) in peer.transfers or isinstance(
            peer.memory.get(Direction.SEND, transfer_id, now), _Tombstone
        ):
            # `transfer_id` trùng lượt chiều ngược lại với cùng thiết bị.
            self._send(peer, Cancel(transfer_id, CancelReason.ERROR))
            stone = _Tombstone(CancelReason.ERROR, False, now, self._order())
            self._remember(peer, Direction.RECEIVE, transfer_id, stone)
            return
        if not self._receiving:
            self._send(peer, Reject(transfer_id, RejectReason.NOT_RECEIVING))
            return
        if len(peer.offers) >= MAX_QUEUED_OFFERS:
            self._send(peer, Reject(transfer_id, RejectReason.BUSY))
            return
        new = _Recv(
            key=TransferKey(peer.device_id, Direction.RECEIVE, transfer_id),
            offer=msg,
            names=tuple(dedupe_offer_names([entry.name for entry in msg.files])),
            total_size=sum(entry.size for entry in msg.files),
        )
        self._add_transfer(peer, new)
        becomes_head = peer.running is None and not peer.offers
        peer.offers.append(new)
        if becomes_head:
            self._check_space(peer, new)

    def _check_space(self, peer: _Peer, t: _Recv) -> None:
        t.phase = _Phase.CHECKING
        self._emit_check_space(t)

    def _emit_check_space(self, t: _Recv) -> None:
        """`CheckSpace` với `check_id` mới; kết quả của mọi lần kiểm trước của lượt bị bỏ."""
        t.check_id = self._next_check_id
        self._next_check_id += 1
        self._emit(CheckSpace(t.key.device_id, t.key.transfer_id, t.total_size, t.check_id))

    def _accept_offer(self, peer: _Peer, t: _Recv, now: float) -> None:
        """Chấp nhận `offer` đang hỏi (người dùng đã nhận, đủ chỗ trên thư mục nhận hiện tại)."""
        peer.offers.remove(t)
        t.phase = _Phase.RUNNING
        peer.running = t
        t.owns_temp = True
        self._emit(CreateTemp(peer.device_id, t.key.transfer_id, t.offer))
        self._start_file(peer, t, 0, now)  # `accept` và `resume` chờ `temp_created`

    def _advance_queue(self, peer: _Peer) -> None:
        """Không còn lượt đang chạy và hàng không có đầu: `offer` xếp hàng cũ nhất được xét."""
        if peer.running is None and peer.offers and peer.offers[0].phase is _Phase.QUEUED:
            self._check_space(peer, peer.offers[0])

    def _fail_done(self, peer: _Peer, transfer_id: str, now: float) -> None:
        """Lỗi khi so với `offer` của lượt nhận đã xong: không còn gì để hủy, chỉ trả
        `cancel{error}` và nhớ bia mộ đè lên (protocol §6.3)."""
        self._send(peer, Cancel(transfer_id, CancelReason.ERROR))
        stone = _Tombstone(CancelReason.ERROR, False, now, self._order())
        self._remember(peer, Direction.RECEIVE, transfer_id, stone)

    def _on_complete(self, peer: _Peer, msg: Complete, now: float) -> None:
        """`complete` (protocol §6.3, cột “Nhận”, luật 1, 5, 6, 7; §4.4)."""
        transfer_id, index = msg.transfer_id, msg.file_index
        memo = peer.memory.get(Direction.RECEIVE, transfer_id, now)
        if isinstance(memo, _Tombstone):
            self._send(peer, Cancel(transfer_id, memo.reason))
            return
        t = peer.transfers.get((Direction.RECEIVE, transfer_id))
        if isinstance(t, _Recv) and (t.phase is not _Phase.RUNNING or not t.created):
            # Luật 5; chưa `temp_created` thì máy gửi chưa thể có `accept`/`resume` nào của lượt.
            self._fail(t, CancelReason.ERROR, FailureDetail.PROTOCOL, now)
            return
        if isinstance(memo, _DoneMemo):
            if index < memo.n_files:
                self._send(peer, Verified(transfer_id, index))
            else:
                self._fail_done(peer, transfer_id, now)  # `file_index` không nhỏ hơn số file
            return
        if not isinstance(t, _Recv):
            self._send(peer, Cancel(transfer_id, CancelReason.UNKNOWN_TRANSFER))
            return
        if index < t.file_index:
            self._send(peer, Verified(transfer_id, index))
            return
        if index >= len(t.offer.files):
            self._fail(t, CancelReason.ERROR, FailureDetail.PROTOCOL, now, file_index=None)
            return
        root = bytes.fromhex(msg.merkle_root)
        if index > t.file_index or (t.root is not None and t.root != root):
            self._fail(t, CancelReason.ERROR, FailureDetail.PROTOCOL, now)
            return
        t.root = root
        self._maybe_reread(peer, t)

    def _start_file(self, peer: _Peer, t: _Recv, index: int, now: float) -> None:
        """Bắt đầu nhận file `index`: `OpenPart`, trạng thái mới, xin `resume` ngay."""
        t.resume_at = None
        t.file_index = index
        size = t.offer.files[index].size
        n = block_count(size)
        self._emit(OpenPart(peer.device_id, t.key.transfer_id, index, size))
        t.size_f = size
        t.n_f = n
        t.bits = Bitfield(n)
        t.leaves = bytearray(DIGEST_SIZE * n)
        t.have_count = 0
        t.have_bytes = 0
        t.pending = set()
        t.pending_bytes = 0
        t.unbatched = []
        t.batches = {}
        t.hw = -1
        t.root = None
        t.bad_count = 0
        t.verify_failures = 0
        t.idle_rounds = 0
        t.rereading = False
        t.finalizing = False
        self._request_resume(peer, t, now)

    def _request_resume(self, peer: _Peer, t: _Recv, now: float) -> None:
        """Xin `resume` ngay: đóng kết nối dữ liệu của lượt, `fsync` phần còn lại rồi mới gửi.

        Từ lúc này `resume` cũ hết hiệu lực (`last_resume = None`): trong lúc chờ `fsync`, kết nối
        dữ liệu của `resume` cũ bị từ chối, nên không có khối mới tới và `resume` mới không xin lại
        khối đã ghi (protocol §4.1, §4.3).
        """
        t.resume_at = None
        t.open_wait_at = None
        t.last_resume = None
        if t.conn is not None:
            self._close_conn(t.conn)
        if t.unbatched:
            self._push_batch(peer, t)
        t.want_resume = True
        if peer.control is not None and not t.batches and t.created:
            self._send_resume(peer, t, now)  # chưa `temp_created`: giữ tới `temp_created`

    def _send_resume(self, peer: _Peer, t: _Recv, now: float) -> None:
        """Gửi `resume` cho file hiện tại. Thiếu khối: là client thì mở kết nối dữ liệu; là server
        thì chờ `data_open` khớp tới `now + DATA_OPEN_WAIT` (quá hạn ở `tick` → hẹn `resume` mới
        theo lịch §6.2), để bên gửi đã ghi xong vào một kết nối bị cắt trước khi tới đây không làm
        lượt treo (protocol §4.1).
        """
        assert peer.control is not None
        if t.conn is not None:
            self._close_conn(t.conn)  # phòng thủ: `resume` mới thay kết nối của `resume` cũ
        seq = peer.next_seq
        peer.next_seq += 1
        full = t.have_count == t.n_f
        transfer_id = t.key.transfer_id
        self._send(peer, Resume(transfer_id, t.file_index, seq, t.bits.to_base64()))
        t.last_resume = (t.file_index, seq, full)
        t.sent_resume = True
        t.want_resume = False
        t.open_wait_at = None
        control_id, client = peer.control
        if full:
            return
        if client:
            self._emit(OpenData(peer.device_id, control_id, DataOpen(transfer_id, t.file_index, seq)))
        else:
            t.open_wait_at = now + DATA_OPEN_WAIT

    def _push_batch(self, peer: _Peer, t: _Recv) -> None:
        """Đẩy lô khối đã ghi mà chưa vào lô: `SyncPart` với token mới."""
        token = self._next_token
        self._next_token += 1
        batch = t.unbatched
        t.unbatched = []
        t.batches[token] = batch
        self._emit(SyncPart(peer.device_id, t.key.transfer_id, t.file_index, token, tuple(batch)))

    def _bad_block(self, peer: _Peer, t: _Recv, now: float) -> None:
        """Khối sai trên kết nối hiện tại: đóng, đếm, quá trần thì hủy, không thì xin `resume` ngay."""
        t.bad_count += 1
        if t.conn is not None:
            self._close_conn(t.conn)
        if t.bad_count > MAX_BAD_BLOCKS:
            self._fail(t, CancelReason.ERROR, FailureDetail.CORRUPT_BLOCKS, now, file_index=t.file_index)
        else:
            self._request_resume(peer, t, now)

    def _maybe_reread(self, peer: _Peer, t: _Recv) -> None:
        """Đủ bit, có root, không còn khối chờ `fsync`, chưa đọc lại hay đổi tên → `Reread`."""
        if (
            t.have_count == t.n_f
            and t.root is not None
            and not t.pending
            and not t.rereading
            and not t.finalizing
        ):
            t.rereading = True
            self._emit(Reread(peer.device_id, t.key.transfer_id, t.file_index, t.leaves))
