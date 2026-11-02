"""Hiện chữ cho người dùng: tên do máy kia tự đặt, tên file, dung lượng, thời gian.

Tên thiết bị: luật ở docs/mvp.md mục 7.2. Tên trong `hello` chưa được xác thực
(docs/protocol.md mục 3.3): kẻ đứng giữa có thể đặt tên trông như một mã ghép đôi, chèn ký tự
trông như khoảng trắng để đẩy chữ ra xa, hoặc chèn ký tự đổi hướng chữ (RLO U+202E…) để đảo
hướng câu đứng sau tên. `display_name` làm những ký tự đó lộ ra (thành `·`) và giữ tên trong
`DISPLAY_NAME_WIDTH` cột. Ngoặc “…” và vị trí của tên (luôn sau mã) do người gọi lo.

Ký tự thành `·` (`_shown`, chung cho tên máy và tên file): ký tự trống (`_is_blank`), ký tự
mà `core.filenames` bỏ khi làm sạch (`INVISIBLE_CHARS`: điều khiển hướng chữ, ký tự vô hình,
U+2028/U+2029) và mọi ký tự định dạng khác (loại Cf) trừ ZWJ U+200D và ZWNJ U+200C (emoji
ghép và chữ Ba Tư cần chúng). Tên máy đã qua `validate_device_name` vẫn được thay, để không
phụ thuộc một tầng kiểm tra duy nhất.

Tên file (`display_filename`, docs/mvp.md mục 7.3): cùng luật ký tự, nhưng cắt ở giữa và giữ
đuôi (phần mở rộng), tối đa `FILE_NAME_WIDTH` cột. Không thay ký tự điều khiển (Cc): tên file
nhận đã được làm sạch, tên file cục bộ do bên gọi thay trước khi in.

Dung lượng (`format_size`) theo hệ nhị phân của docs/mvp.md mục 8; thời gian (`format_duration`)
cho “còn … ” của dòng tiến độ.

Độ rộng chỉ là ước lượng cho terminal và giao diện: `east_asian_width` W/F = 2 cột; dấu kết
hợp (Mn, Me) và ZWJ (U+200D) = 0 cột, kể cả khi dấu đó cũng thuộc loại rộng; còn lại 1 cột.
"""

from __future__ import annotations

import math
import unicodedata

from teleport.core.filenames import INVISIBLE_CHARS
from teleport.core.numbers import is_finite

DISPLAY_NAME_WIDTH = 32  # mvp mục 7.2: tên dài hơn bị cắt, tổng cả `…` vẫn ≤ 32 cột
FILE_NAME_WIDTH = 48  # mvp mục 7.3: tên file dài hơn bị cắt ở giữa, tổng cả `…` vẫn ≤ 48 cột
BLANK_MARK = "·"  # ·

_ELLIPSIS = "…"  # … (1 cột)
_ZWJ = "\u200d"  # ZWJ, viết bằng escape để mã nguồn không chứa ký tự ẩn
# Ngoài khoảng trắng Unicode (loại Zs): các ký tự hiện ra trống trơn dù không phải khoảng trắng.
_EXTRA_BLANKS = frozenset("\u2800\u3164\u115f\u1160\uffa0")  # chữ nổi trống, các ký tự lấp chỗ Hangul
# Ký tự loại Cf được giữ nguyên khi hiện: ZWJ và ZWNJ, cùng luật với `core.filenames`.
_KEPT_FORMAT_CHARS = frozenset((_ZWJ, "\u200c"))
_SIZE_UNITS = ("KB", "MB", "GB", "TB")  # mvp mục 8: 1 KB = 1024 byte, 1 MB = 1024 KB…


def _is_blank(ch: str) -> bool:
    """Ký tự trông như khoảng trắng mà không phải dấu cách thường U+0020."""
    return ch in _EXTRA_BLANKS or (ch != " " and unicodedata.category(ch) == "Zs")


def _is_hidden(ch: str) -> bool:
    """Ký tự vô hình hay đổi hướng chữ: `INVISIBLE_CHARS` và loại Cf, trừ ZWJ và ZWNJ."""
    if ch in INVISIBLE_CHARS:
        return True
    return ch not in _KEPT_FORMAT_CHARS and unicodedata.category(ch) == "Cf"


def _shown(text: str) -> str:
    """`text` với ký tự trống và ký tự vô hình / đổi hướng chữ thay bằng `BLANK_MARK`."""
    return "".join(BLANK_MARK if _is_blank(ch) or _is_hidden(ch) else ch for ch in text)


def _width(ch: str) -> int:
    """Số cột của một ký tự (xem docstring của module)."""
    if ch == _ZWJ or unicodedata.category(ch) in ("Mn", "Me"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_name(name: str, *, max_width: int = DISPLAY_NAME_WIDTH) -> str:
    """Tên để hiện cho người dùng: ký tự lạ thành `·`, dài quá `max_width` cột thì cắt.

    Mọi ký tự loại Zs trừ U+0020, cùng U+2800, U+3164, U+115F, U+1160, U+FFA0, và ký tự vô hình
    / đổi hướng chữ (`INVISIBLE_CHARS`, loại Cf trừ ZWJ và ZWNJ) thành `BLANK_MARK` (1 cột);
    độ rộng đo sau bước này. Vượt `max_width` thì giữ phần đầu dài nhất sao cho phần đó + `…`
    ≤ `max_width` cột, bỏ ZWJ thừa ở cuối phần giữ lại.
    Không thêm ngoặc. `name` không phải chuỗi → TypeError; `max_width < 2` → ValueError.
    """
    if not isinstance(name, str):
        raise TypeError("name phải là chuỗi")
    if max_width < 2:
        raise ValueError("max_width phải ≥ 2")
    shown = _shown(name)
    widths = [_width(ch) for ch in shown]
    if sum(widths) <= max_width:
        return shown
    budget = max_width - 1  # chừa 1 cột cho `…`
    used = 0
    end = 0
    for width in widths:
        if used + width > budget:
            break
        used += width
        end += 1
    return shown[:end].rstrip(_ZWJ) + _ELLIPSIS


def text_width(text: str) -> int:
    """Số cột của cả chuỗi (cộng `_width` từng ký tự)."""
    return sum(_width(ch) for ch in text)


def display_filename(name: str, *, max_width: int = FILE_NAME_WIDTH) -> str:
    """Tên file để hiện: thay ký tự như `display_name`, dài quá `max_width` cột thì cắt ở giữa.

    Ký tự trống, ký tự trong `core.filenames.INVISIBLE_CHARS` (điều khiển hướng chữ,
    U+2028/U+2029, U+200B, U+FEFF, U+2060…) và loại Cf trừ ZWJ, ZWNJ thành `·`.

    Cắt: giữ phần cuối dài nhất ≤ nửa ngân sách (làm tròn lên) và phần đầu dài nhất trong phần
    ngân sách còn lại, nối bằng `…` (1 cột), nên đuôi file (phần mở rộng) vẫn còn và tổng ≤
    `max_width` cột. Bỏ ZWJ thừa ở cuối phần đầu, và ký tự 0 cột ở đầu phần cuối (dấu kết hợp
    không dính vào `…`). `name` không phải chuỗi → TypeError; `max_width < 2` → ValueError.
    """
    if not isinstance(name, str):
        raise TypeError("name phải là chuỗi")
    if max_width < 2:
        raise ValueError("max_width phải ≥ 2")
    shown = _shown(name)
    widths = [_width(ch) for ch in shown]
    if sum(widths) <= max_width:
        return shown
    budget = max_width - 1  # chừa 1 cột cho `…`
    tail_used = 0
    start = len(shown)
    for width in reversed(widths):
        if tail_used + width > (budget + 1) // 2:
            break
        tail_used += width
        start -= 1
    head_used = 0
    end = 0
    for width in widths[:start]:
        if head_used + width > budget - tail_used:
            break
        head_used += width
        end += 1
    tail = shown[start:]
    while tail and _width(tail[0]) == 0:
        tail = tail[1:]
    return shown[:end].rstrip(_ZWJ) + _ELLIPSIS + tail


def _round_half_up(numerator: int, denominator: int) -> int:
    return (2 * numerator + denominator) // (2 * denominator)


def format_size(size: int, *, trim: bool = False) -> str:
    """Dung lượng theo hệ nhị phân (mvp mục 8): “512 byte”, “2,1 MB”, “380 KB”, “8,0 GB”.

    Dưới 1024 byte: “N byte”. Còn lại: đơn vị lớn nhất (tới TB) mà giá trị ≥ 1; giá trị < 100
    có một chữ số thập phân (dấu phẩy), ≥ 100 là số nguyên; làm tròn nửa lên, chạm 1024 thì lên
    đơn vị kế. `trim`: bỏ “,0” (“4 GB”, dùng cho giới hạn). Không phải số nguyên → TypeError;
    âm → ValueError.
    """
    if isinstance(size, bool) or not isinstance(size, int):
        raise TypeError("size phải là số nguyên")
    if size < 0:
        raise ValueError("size phải ≥ 0")
    if size < 1024:
        return f"{size} byte"
    unit = 0
    while unit < len(_SIZE_UNITS) - 1 and size >= 1024 ** (unit + 2):
        unit += 1
    while True:
        base = 1024 ** (unit + 1)
        tenths = _round_half_up(size * 10, base)
        if tenths < 1000:
            whole, frac = divmod(tenths, 10)
            text = str(whole) if trim and frac == 0 else f"{whole},{frac}"
            return f"{text} {_SIZE_UNITS[unit]}"
        whole = _round_half_up(size, base)
        if whole >= 1024 and unit < len(_SIZE_UNITS) - 1:
            unit += 1  # làm tròn chạm 1024: lên đơn vị kế (“1,0 MB”)
            continue
        return f"{whole} {_SIZE_UNITS[unit]}"


def format_duration(seconds: float) -> str:
    """Khoảng thời gian: “45 giây”, “2 phút 10 giây”, “1 giờ 5 phút”, “2 ngày 3 giờ”.

    Làm tròn tới giây (nửa lên); chỉ hai đơn vị lớn nhất, bỏ đơn vị sau khi nó bằng 0
    (“2 phút”). Âm tính là 0. Không phải số → TypeError; NaN hay vô hạn → ValueError.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, int | float):
        raise TypeError("seconds phải là số")
    if not is_finite(seconds):
        raise ValueError("seconds phải là số hữu hạn")
    total = max(0, math.floor(seconds + 0.5))
    if total < 60:
        return f"{total} giây"
    for size, big, small_size, small in (
        (86400, "ngày", 3600, "giờ"),
        (3600, "giờ", 60, "phút"),
        (60, "phút", 1, "giây"),
    ):
        if total >= size:
            major, rest = divmod(total, size)
            minor = rest // small_size
            return f"{major} {big}" if minor == 0 else f"{major} {big} {minor} {small}"
    raise AssertionError("không tới đây")
