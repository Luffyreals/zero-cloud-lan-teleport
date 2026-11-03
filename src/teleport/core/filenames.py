"""Tên file trong `offer`: làm sạch ở bên nhận, chuẩn bị ở bên gửi, đánh số khi trùng.

Luật ở docs/ke_hoach.md mục 3.3 và docs/protocol.md mục 3.3, 4.4. Tên file do máy kia gửi
không bao giờ được tin: `sanitize_filename` **biến đổi** mọi chuỗi thành một tên an toàn để
đặt trong thư mục nhận, không bao giờ từ chối. Từ chối message (tên quá 255 byte UTF-8, có ký
tự loại Cc/Cs; tên rỗng vẫn hợp lệ) là việc của `teleport.core.messages`.

Thứ tự làm sạch (mỗi bước giữ được điều các bước trước đã bảo đảm):
1. Bỏ ký tự loại Cc (điều khiển, kể cả mã 0–31), Cs (surrogate lẻ), ký tự điều khiển hướng chữ
   và ký tự vô hình (`_DROPPED_CHARS`).
2. Chuẩn hóa NFC (macOS lưu NFD).
3. Chỉ giữ phần sau dấu `/` hoặc `\\` cuối cùng: `../../x` → `x`, `C:\\Windows\\x` → `x`,
   `\\\\?\\C:\\x` → `x`, `a/b/` → rỗng.
4. Bỏ ký tự ổ đĩa ở đầu (`C:x` → `x`).
5. Thay ký tự cấm trên Windows `<>:"|?*` bằng `_` (`:` còn mở alternate data stream trên NTFS).
6. Cắt còn ≤ `MAX_NAME_BYTES` byte UTF-8, giữ đuôi file, không cắt giữa một ký tự.
7. Bỏ dấu chấm và dấu cách U+0020 ở cuối (Windows tự cắt, hai tên khác nhau có thể thành một).
8. Rỗng → `FALLBACK_NAME`.
9. Tên thiết bị của Windows (`CON`, `NUL.txt`, `con .txt`, `COM¹`…) hoặc tên thư mục tạm
   `.teleport` → thêm `_` ở đầu (rồi cắt lại nếu vượt 255 byte).

Tên kiểu `x.mp4.part` hay `x.part.state` được giữ nguyên: file tạm nằm trong
`<thư mục nhận>/.teleport/<transfer_id>/` (`TEMP_DIR_NAME`) nên không bao giờ đụng tên file
nhận được (ke_hoach mục 3.3); chỉ chính tên `.teleport` mới trùng tên nội bộ.

API khác:
- `numbered`: tên thứ `n` khi trùng (` (1)`, ` (2)`…); `dedupe_offer_names`: khử trùng các tên
  trong một `offer`; `dedupe_key`: khóa so trùng (NFC + casefold), dùng cả khi so với file đã có.
- `fit_filename`: tên đã làm sạch, cắt vừa một ngân sách byte nhỏ hơn 255 mà vẫn ổn định qua
  `sanitize_filename`; `fallback_filename`: tên dự phòng chỉ gồm ASCII, ≤ `FALLBACK_MAX_BYTES`
  byte, dùng khi hệ file từ chối tên.
- `prepare_outgoing_name`: bên gửi kiểm và cắt tên.

Giới hạn độ dài của cả đường dẫn (Windows `MAX_PATH`) và tên dự phòng khi hệ file từ chối tên
không thuộc module này: `teleport.app.storage` lo (docs/architecture.md mục 4 “Thư mục nhận”).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

MAX_NAME_BYTES = 255  # protocol mục 3.3: `name` ≤ 255 byte UTF-8
FALLBACK_NAME = "file"  # tên rỗng sau khi làm sạch
TEMP_DIR_NAME = ".teleport"  # thư mục file tạm trong thư mục nhận (architecture mục 4)
# Trần độ dài tên dự phòng, byte (architecture mục 4 “Thư mục nhận”).
FALLBACK_MAX_BYTES = 64
# Đuôi file dài hơn thì coi như không có đuôi: khi cắt tên chỉ giữ đuôi ngắn, kiểu `.mp4`,
# `.sublime-project`; tên lạ như `a.<200 ký tự>` bị cắt ở cuối như tên không đuôi.
MAX_EXTENSION_BYTES = 32

# Ký tự bị bỏ, ngoài loại Cc và Cs: cùng tập cấm ở tên thiết bị (protocol mục 3.3) cộng
# U+061C (ALM). Đó là toàn bộ ký tự có thuộc tính Unicode Bidi_Control, dùng để giả mạo tên
# (ví dụ "anh<U+202E>gpj.exe" hiện thành "anhexe.jpg"), cùng các ký tự vô hình và xuống dòng
# Unicode. ZWJ U+200D và ZWNJ U+200C được giữ vì emoji ghép và chữ Ba Tư cần chúng.
# Viết bằng escape để mã nguồn không chứa ký tự ẩn (kiểu tấn công "trojan source").
_DROPPED_CHARS = frozenset(
    "\u2028\u2029"  # phân cách dòng / đoạn
    "\u200b\ufeff\u2060"  # khoảng trắng độ rộng 0, BOM, word joiner
    "\u061c\u200e\u200f"  # ALM, LRM, RLM
    "\u202a\u202b\u202c\u202d\u202e"  # LRE, RLE, PDF, LRO, RLO
    "\u2066\u2067\u2068\u2069"  # LRI, RLI, FSI, PDI
)
# Tên công khai của cùng tập ký tự: `core.display` và `cli` trung hòa chúng khi in (phòng thủ chiều sâu).
INVISIBLE_CHARS = _DROPPED_CHARS
_DROPPED_CATEGORIES = frozenset({"Cc", "Cs"})
_OUTGOING_FORBIDDEN_CATEGORIES = _DROPPED_CATEGORIES  # bên gửi: protocol mục 3.3

_SEPARATORS_RE = re.compile(r"[/\\]")
_DRIVE_RE = re.compile(r"[A-Za-z]:")  # chỉ chữ ASCII: ký tự ổ đĩa của Windows
_WINDOWS_FORBIDDEN = str.maketrans(dict.fromkeys('<>:"|?*', "_"))
_TRAILING_STRIPPED = ". "  # Windows tự cắt dấu chấm và dấu cách U+0020 ở cuối tên
# Tên thiết bị của Windows, so trên phần trước dấu chấm đầu tiên, đã bỏ dấu cách hai đầu và
# viết hoa. ¹²³ (U+00B9, U+00B2, U+00B3) được Windows coi là chữ số ở COM/LPT. CONIN$, CONOUT$
# mở console. Nhận thừa (đổi tên một tên vô hại) không sao; nhận thiếu thì không được.
_RESERVED_STEM_RE = re.compile(r"CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[0-9\u00b9\u00b2\u00b3]")
_INTERNAL_NAMES = frozenset({TEMP_DIR_NAME})  # so bằng casefold
_RESERVED_PREFIX = "_"


class OutgoingNameError(ValueError):
    """Bên gửi không gửi được tên này: rỗng, hoặc chứa ký tự loại Cc / Cs (mvp F4)."""


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _cut_utf8(text: str, max_bytes: int) -> str:
    """Phần đầu dài nhất của `text` có ≤ `max_bytes` byte UTF-8, không cắt giữa một ký tự."""
    return text.encode("utf-8")[: max(max_bytes, 0)].decode("utf-8", "ignore")


def _split_ext(name: str) -> tuple[str, str]:
    """Tách (phần trước đuôi, đuôi) như `os.path.splitext`; đuôi > `MAX_EXTENSION_BYTES` → không đuôi.

    Dấu chấm ở đầu tên không mở đầu đuôi: `.bashrc` → (`.bashrc`, ``).
    """
    start = len(name) - len(name.lstrip("."))
    dot = name.rfind(".")
    if dot <= start:
        return name, ""
    ext = name[dot:]
    if _utf8_len(ext) > MAX_EXTENSION_BYTES:
        return name, ""
    return name[:dot], ext


def _fit(name: str, max_bytes: int, suffix: str = "") -> str:
    """`stem + suffix + ext` trong `max_bytes` byte, cắt phần trước đuôi khi cần.

    Phần trước đuôi phải còn ít nhất một ký tự; không đủ chỗ thì bỏ đuôi và cắt cả tên ở cuối.
    Không đủ chỗ cho một ký tự + `suffix` → ValueError.
    """
    if _utf8_len(name) + _utf8_len(suffix) <= max_bytes:
        stem, ext = _split_ext(name)
        return stem + suffix + ext
    stem, ext = _split_ext(name)
    for head, tail in ((stem, ext), (name, "")):
        budget = max_bytes - _utf8_len(suffix) - _utf8_len(tail)
        cut = _cut_utf8(head, budget)
        if cut:
            return cut + suffix + tail
    raise ValueError(f"max_bytes = {max_bytes} không đủ chỗ cho tên và hậu tố {suffix!r}")


def _is_reserved(name: str) -> bool:
    """Tên thiết bị của Windows (kể cả có đuôi) hoặc trùng tên nội bộ `.teleport`."""
    if name.casefold() in _INTERNAL_NAMES:
        return True
    stem = name.split(".", 1)[0].strip(" ").upper()
    return _RESERVED_STEM_RE.fullmatch(stem) is not None


def sanitize_filename(name: str) -> str:
    """Tên an toàn để đặt trong thư mục nhận, làm từ tên do máy kia gửi. Không bao giờ từ chối.

    Kết quả: NFC, 1–255 byte UTF-8, không chứa `/`, `\\`, ký tự cấm trên Windows, ký tự loại
    Cc/Cs, ký tự điều khiển hướng chữ hay ký tự vô hình; không kết thúc bằng `.` hay dấu cách;
    không phải tên thiết bị của Windows hay `.teleport`. Gọi lại trên kết quả không đổi gì.
    Các bước: docstring của module. `name` không phải chuỗi → TypeError.
    """
    if not isinstance(name, str):
        raise TypeError("name phải là chuỗi")
    kept = "".join(
        ch for ch in name if ch not in _DROPPED_CHARS and unicodedata.category(ch) not in _DROPPED_CATEGORIES
    )
    kept = unicodedata.normalize("NFC", kept)
    kept = _SEPARATORS_RE.split(kept)[-1]
    if _DRIVE_RE.match(kept):
        kept = kept[2:]
    kept = kept.translate(_WINDOWS_FORBIDDEN)
    kept = _fit(kept, MAX_NAME_BYTES).rstrip(_TRAILING_STRIPPED)
    if not kept:
        return FALLBACK_NAME
    if _is_reserved(kept):
        # Tên bắt đầu bằng `_` không bao giờ là tên thiết bị hay `.teleport`, và cắt ở cuối
        # không bỏ được ký tự đầu, nên một lần là đủ.
        kept = _fit(_RESERVED_PREFIX + kept, MAX_NAME_BYTES).rstrip(_TRAILING_STRIPPED)
    return kept


def numbered(name: str, n: int, *, max_bytes: int = MAX_NAME_BYTES) -> str:
    """Tên thứ `n` khi trùng: `a.txt` → `a (1).txt`, `.bashrc` → `.bashrc (1)`.

    `name` được làm sạch trước (`sanitize_filename`). Kết quả ≤ `max_bytes` byte UTF-8 (cắt
    phần trước đuôi khi cần, giữ đuôi) và đi qua `sanitize_filename` không đổi.
    `n` không phải số nguyên ≥ 1, hoặc `max_bytes` không trong 1…`MAX_NAME_BYTES`, hoặc quá
    nhỏ để chứa một ký tự + ` (n)` → ValueError.
    """
    if type(n) is not int or n < 1:
        raise ValueError("n phải là số nguyên ≥ 1")
    limit = _check_max_bytes(max_bytes)
    return _fit(sanitize_filename(name), limit, f" ({n})")


def _check_max_bytes(max_bytes: object) -> int:
    # bool là lớp con của int: bị từ chối như mọi kiểu khác.
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_NAME_BYTES:
        raise ValueError(f"max_bytes phải là số nguyên 1…{MAX_NAME_BYTES}")
    return max_bytes


# Cắt rồi làm sạch lại hội tụ sau tối đa 3 vòng: làm sạch chỉ làm tên dài ra khi thêm `_` ở đầu
# (một lần, vì cắt ở cuối không bỏ được ký tự đầu) hay khi tên thành rỗng → `file`.
_FIT_ROUNDS = 8


def fit_filename(name: str, max_bytes: int = MAX_NAME_BYTES) -> str:
    """Tên đã làm sạch, cắt còn ≤ `max_bytes` byte UTF-8 (tầng `app` dùng khi đường dẫn dài).

    Làm sạch (`sanitize_filename`), cắt như `numbered` (cắt phần trước đuôi, giữ đuôi; không đủ
    chỗ thì bỏ đuôi và cắt ở cuối), rồi làm sạch lại tới khi ổn định: cắt có thể để lại `.` hay
    dấu cách ở cuối, hoặc tạo ra tên thiết bị (`CONabc.txt` cắt còn 7 byte là `CON.txt`, thành
    `_CO.txt`). Kết quả không rỗng, đi qua `sanitize_filename` không đổi, không phải tên thiết
    bị của Windows hay `.teleport`; `fit_filename(x, MAX_NAME_BYTES) == sanitize_filename(x)`.
    `max_bytes` không phải số nguyên 1…`MAX_NAME_BYTES`, hoặc quá nhỏ để thỏa các điều trên
    (chỉ có thể khi < 4) → ValueError. `name` không phải chuỗi → TypeError.
    """
    limit = _check_max_bytes(max_bytes)
    fitted = sanitize_filename(name)
    for _ in range(_FIT_ROUNDS):
        if _utf8_len(fitted) <= limit:
            return fitted
        fitted = sanitize_filename(_fit(fitted, limit))
    raise ValueError(f"không cắt được tên còn ≤ {limit} byte")


def fallback_filename(name: str, max_bytes: int = FALLBACK_MAX_BYTES) -> str:
    """Tên dự phòng khi hệ file từ chối tên (architecture mục 4 “Thư mục nhận”).

    Làm sạch, thay **mọi** ký tự ngoài ASCII bằng `_`, rồi `fit_filename` với
    `min(max_bytes, FALLBACK_MAX_BYTES)`: kết quả chỉ gồm ASCII, ổn định qua `sanitize_filename`
    và giữ đuôi ASCII (`Ảnh 𘷳.jpg` → `_nh _.jpg`). Ràng buộc tham số như `fit_filename`.
    """
    limit = _check_max_bytes(max_bytes)
    ascii_only = "".join(ch if ch.isascii() else "_" for ch in sanitize_filename(name))
    return fit_filename(ascii_only, min(limit, FALLBACK_MAX_BYTES))


def dedupe_key(name: str) -> str:
    """Khóa so trùng tên: không phân biệt hoa thường (casefold), sau NFC.

    Dùng cho cả các tên trong một `offer` lẫn khi so với file đã có trong thư mục nhận.
    """
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", name).casefold())


def dedupe_offer_names(names: Sequence[str]) -> list[str]:
    """Làm sạch từng tên của một `offer` rồi khử trùng, cùng thứ tự.

    Hai tên trùng nhau sau khi làm sạch (không phân biệt hoa thường, sau NFC): tên đầu giữ
    nguyên, các tên sau thành ` (1)`, ` (2)`… Số được chọn để không trùng bất kỳ tên nào
    khác trong `offer`, kể cả tên đứng sau: `[a.txt, a.txt, a (1).txt]` →
    `[a.txt, a (2).txt, a (1).txt]`. Trùng với file đã có trên đĩa do `app` lo.

    Độ phức tạp gần tuyến tính theo số tên, kể cả khi nhiều tên dài khác nhau bị cắt thành cùng
    một tên đánh số (`_numbering_key`).
    """
    cleaned = [sanitize_filename(name) for name in names]
    keys = [dedupe_key(name) for name in cleaned]
    taken = set(keys)  # mọi tên gốc giữ chỗ trước, tên đánh số không được lấy của chúng
    seen: set[str] = set()
    # `restore` chạy lại hàm này cho lượt đã lưu (`core.transfer`), nên kết quả phải giống hệt
    # thuật toán cũ: mỗi khóa tên gốc nhớ `group_next`, tên trùng lấy số n ≥ `group_next` nhỏ
    # nhất mà tên đánh số chưa nằm trong `taken`. `band_next` chỉ là đường tắt: khóa của một dải
    # số cùng số chữ số → số mà mọi số nhỏ hơn trong dải đều đã nằm trong `taken` (`taken` chỉ
    # lớn dần), nên nhảy qua chúng không đổi kết quả.
    group_next: dict[str, int] = {}
    band_next: dict[str, int] = {}
    result: list[str] = []
    for name, key in zip(cleaned, keys, strict=True):
        if key not in seen:
            seen.add(key)
            result.append(name)
            continue
        start = group_next.get(key, 1)
        found: str | None = None
        digits = 1
        while found is None:
            low, high = 10 ** (digits - 1), 10**digits
            digits += 1
            if high <= start:
                continue
            band_key = _numbering_key(name, digits - 1)
            known = max(low, band_next.get(band_key, low))
            n = max(start, known)
            while n < high:
                candidate = numbered(name, n)
                n += 1
                if dedupe_key(candidate) not in taken:
                    found = candidate
                    break
            # Mọi số từ `max(start, known)` tới trước `n` đều đã bị lấy; chỉ nối dài được đường
            # tắt khi đoạn đó liền với nó (`start ≤ known`).
            if start <= known:
                band_next[band_key] = n
        group_next[key] = n
        taken.add(dedupe_key(found))
        result.append(found)
    return result


def _numbering_key(name: str, digits: int) -> str:
    """Khóa chung của các tên đánh số có `digits` chữ số làm từ tên đã làm sạch `name`.

    Trong một dải số cùng số chữ số, `numbered(name, n)` có dạng `P + " (n)" + E` với `P`, `E`
    chỉ phụ thuộc `name` và độ dài byte của hậu tố, vì `_fit` chỉ dùng độ dài đó. Thay hậu tố
    bằng chừng ấy ký tự NUL (không thể có trong tên đã làm sạch) cho một chuỗi xác định đúng
    cặp (`P`, `E`): hai tên khác nhau nhưng bị cắt thành cùng `P`, `E` dùng chung một bộ đếm,
    nên không phải đếm lại từ đầu qua các số tên kia đã lấy (bậc hai với tên dài 255 byte).
    """
    return dedupe_key(_fit(name, MAX_NAME_BYTES, "\x00" * (3 + digits)))


def prepare_outgoing_name(name: str) -> str:
    """Tên để bên gửi đặt vào `FileEntry.name` (protocol mục 3.3, mvp F4).

    `name` là phần tên cuối của file nguồn. Rỗng hoặc chứa ký tự loại Cc (ví dụ dấu xuống
    dòng) hay Cs (byte không giải mã được, Python giữ dưới dạng surrogate) → `OutgoingNameError`,
    không gửi gì. Dài quá `MAX_NAME_BYTES` byte UTF-8 → cắt phần trước đuôi, giữ đuôi. Không
    làm gì khác: bên nhận tự làm sạch. `name` không phải chuỗi → TypeError.
    """
    if not isinstance(name, str):
        raise TypeError("name phải là chuỗi")
    if not name:
        raise OutgoingNameError("tên file rỗng")
    for ch in name:
        if unicodedata.category(ch) in _OUTGOING_FORBIDDEN_CATEGORIES:
            raise OutgoingNameError(f"tên file chứa ký tự không được phép: U+{ord(ch):04X}")
    return _fit(name, MAX_NAME_BYTES)
