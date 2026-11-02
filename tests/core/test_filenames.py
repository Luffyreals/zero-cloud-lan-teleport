"""Test `teleport.core.filenames`: làm sạch tên file nhận được (P2-2, Giai đoạn 2).

Viết theo đặc tả, không theo code. Nguồn: ke_hoach mục 3.3, mvp F4, protocol mục 3.3 và 4.4,
architecture mục 4 (tên trong `.state` phải không đổi khi qua bộ làm sạch), kế hoạch Giai đoạn 2
mục 4 (API), mục 5 dòng P2-2 (tiêu chí xong), mục 6e (bộ làm sạch biến đổi chứ không từ chối) và
mục 9 (chặn Cs).

Luật kiểm ở đây (chỉ những gì đặc tả quy định; chuỗi đầu ra cụ thể chỉ ép khi đặc tả nói rõ):
- Chỉ giữ phần tên cuối (bỏ mọi `/` và `\\`): `../../x` → `x`, `C:\\Windows\\x` → `x`.
- Kết quả không chứa `<>:"/\\|?*`, ký tự loại Cc, Cs, hay ký tự vô hình / đổi hướng chữ như luật
  tên thiết bị (protocol mục 3.3).
- Không kết thúc bằng dấu chấm hay khoảng trắng; không phải tên thiết bị Windows (kể cả có đuôi,
  kể cả `con .txt`, `COM¹`); không phải `.`/`..`; không trùng thư mục nội bộ `.teleport`
  (không phân biệt hoa thường).
- Đã chuẩn hóa NFC; NFD và NFC của cùng một tên cho cùng kết quả.
- ≤ 255 byte UTF-8 (encode chặt không ném); tên dài thì cắt phần trước đuôi, giữ đuôi.
- Rỗng sau khi làm sạch → `file`. Tên vốn đã sạch thì giữ nguyên. Idempotent.
- `numbered(name, n)`: ` (n)` đứng trước đuôi (`a.txt` → `a (1).txt`), ≤ `max_bytes`.
- `dedupe_offer_names`: khử trùng theo casefold sau NFC, giữ thứ tự, bản đầu giữ tên, bản sau đánh
  số, tên đánh số không đụng tên khác có sẵn trong danh sách.
- `prepare_outgoing_name` (bên gửi): Cc/Cs → `OutgoingNameError`; > 255 byte → cắt, giữ đuôi;
  tên khác giữ nguyên (bên gửi không làm sạch kiểu Windows: việc đó của bên nhận).

Module được import trong fixture, để thiếu module chỉ làm đỏ các test ở đây, không chặn cả bộ test.
"""

import errno
import importlib
import ntpath
import os
import posixpath
import tempfile
import time
import unicodedata

import pytest
from hypothesis import HealthCheck, given, reject, settings
from hypothesis import strategies as st

MAX_BYTES = 255
INTERNAL_DIR = ".teleport"

# Ký tự cấm trên Windows (ke_hoach mục 3.3), ngoài mã 0–31 (đã nằm trong Cc).
FORBIDDEN = frozenset('<>:"/\\|?*')

# Ký tự vô hình / đổi hướng chữ cấm trong tên thiết bị (protocol mục 3.3); ke_hoach mục 3.3 áp
# luật đó cho tên file. Cc và Cs kiểm theo loại Unicode.
INVISIBLE = frozenset(
    [
        "\u2028",
        "\u2029",
        "\u200b",
        "\ufeff",
        "\u2060",
        "\u200e",
        "\u200f",
        *(chr(c) for c in range(0x202A, 0x202F)),
        *(chr(c) for c in range(0x2066, 0x206A)),
        "\u061c",  # ALM: đủ bộ Bidi_Control, tên file bỏ cả ký tự này
    ]
)

# Tên thiết bị Windows theo ke_hoach mục 3.3 (CON, PRN, AUX, NUL, COM1–9, LPT1–9), cộng dạng chữ
# số mũ ¹²³ mà Windows cũng coi là thiết bị (tiêu chí P2-2 có `COM¹`), COM0/LPT0 và CONIN$/CONOUT$.
DEVICE_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{d}" for d in "0123456789\u00b9\u00b2\u00b3"}
    | {f"LPT{d}" for d in "0123456789\u00b9\u00b2\u00b3"}
)


def is_windows_device(name: str) -> bool:
    """Windows xét phần trước dấu chấm đầu tiên, bỏ khoảng trắng cuối, không phân biệt hoa thường."""
    stem = name.split(".", 1)[0].rstrip(" ")
    return stem.upper() in DEVICE_STEMS


def key(name: str) -> str:
    """Khóa so trùng: NFC rồi casefold (kế hoạch mục 4)."""
    return unicodedata.normalize("NFC", name).casefold()


def bad_chars(name: str) -> list[str]:
    return [c for c in name if c in FORBIDDEN or c in INVISIBLE or unicodedata.category(c) in ("Cc", "Cs")]


def assert_safe(out: object) -> None:
    """Mọi tính chất một tên đã làm sạch phải có, bất kể đầu vào."""
    assert isinstance(out, str)
    assert out != ""
    assert len(out.encode("utf-8")) <= MAX_BYTES  # encode chặt: ném nếu còn surrogate lẻ
    assert unicodedata.is_normalized("NFC", out), ascii(out)
    assert bad_chars(out) == [], ascii(out)
    assert not out.endswith((".", " ")), ascii(out)
    assert out not in (".", ".."), ascii(out)
    assert not is_windows_device(out), ascii(out)
    assert key(out) != INTERNAL_DIR, ascii(out)
    # Một thành phần đường dẫn duy nhất, không ổ đĩa, không thoát thư mục trên cả hai kiểu đường dẫn.
    assert posixpath.basename(out) == out
    assert ntpath.basename(out) == out
    assert ntpath.splitdrive(out)[0] == ""
    base = "/recv"
    assert posixpath.dirname(posixpath.normpath(posixpath.join(base, out))) == base
    wbase = "C:\\recv"
    assert ntpath.dirname(ntpath.normpath(ntpath.join(wbase, out))) == wbase


def utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


@pytest.fixture(scope="module")
def fn():
    return importlib.import_module("teleport.core.filenames")


# ---------------------------------------------------------------------------------------------
# sanitize_filename: ca cố định
# ---------------------------------------------------------------------------------------------

# Chỉ giữ phần tên cuối: ke_hoach mục 3.3 quy định rõ, nên ép đúng chuỗi.
LAST_COMPONENT_CASES = [
    ("../../x", "x"),
    ("..\\..\\x", "x"),
    ("C:\\Windows\\x", "x"),
    ("\\\\?\\C:\\x", "x"),
    ("\\\\server\\share\\x.txt", "x.txt"),
    ("/etc/passwd", "passwd"),
    ("a/b\\c.txt", "c.txt"),
]


@pytest.mark.parametrize(("raw", "expected"), LAST_COMPONENT_CASES)
def test_keeps_only_last_path_component(fn, raw, expected):
    assert fn.sanitize_filename(raw) == expected


# Rỗng, hoặc chỉ còn dấu chấm / khoảng trắng (bị bỏ ở cuối) → rỗng → `file`.
@pytest.mark.parametrize("raw", ["", ".", "..", "...", " ", "   ", " . . ", ". .", "../..", "/"])
def test_empty_after_cleaning_becomes_file(fn, raw):
    assert fn.sanitize_filename(raw) == "file"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("x.", "x"), ("x ", "x"), ("x. . ", "x"), ("a.txt.", "a.txt"), ("a.txt  ", "a.txt")],
)
def test_strips_trailing_dots_and_spaces(fn, raw, expected):
    assert fn.sanitize_filename(raw) == expected


# Tên đã sạch (không chạm luật nào) giữ nguyên; tên file tạm không bị đổi vì file tạm nằm trong
# `.teleport/<transfer_id>/` (ke_hoach mục 3.3), không bao giờ đụng tên nhận được.
@pytest.mark.parametrize(
    "raw",
    [
        "a.txt",
        "x.part.state",
        "a.part",
        "x.mp4.part.state",
        "Báo cáo tháng 10.docx",
        "ảnh 🎉.jpg",
        "👨\u200d👩\u200d👧.png",  # ZWJ hợp lệ (luật tên thiết bị cho phép U+200D)
        "a b c.tar.gz",
        "file",
        "CONSOLE.txt",  # bắt đầu bằng CON nhưng không phải tên thiết bị
        "COM10",
        "LPT.txt",
        "teleport",
        ".teleportx",
        "a.teleport",
    ],
)
def test_clean_name_is_unchanged(fn, raw):
    assert fn.sanitize_filename(raw) == raw


@pytest.mark.parametrize(
    ("raw", "ext"),
    [
        ("CON", ""),
        ("con", ""),
        ("Con", ""),
        ("PRN", ""),
        ("AUX", ""),
        ("NUL", ""),
        ("NUL.txt", ".txt"),
        ("nul.tar.gz", ".gz"),
        ("con .txt", ".txt"),
        ("CON  .txt", ".txt"),
        ("CON.", ""),
        ("CON ", ""),
        ("COM1", ""),
        ("com9.dat", ".dat"),
        ("COM\u00b9", ""),
        ("COM\u00b2.txt", ".txt"),
        ("LPT\u00b3", ""),
        ("LPT1", ""),
        ("LPT9.log", ".log"),
        ("COM0", ""),
        ("LPT0.txt", ".txt"),
        ("CONIN$", ""),
        ("conout$.txt", ".txt"),
    ],
)
def test_windows_device_names_are_renamed_keeping_extension(fn, raw, ext):
    out = fn.sanitize_filename(raw)
    assert_safe(out)
    assert out.endswith(ext)


@pytest.mark.parametrize("raw", [".teleport", ".TELEPORT", ".Teleport", ".teleport.", ".teleport "])
def test_internal_temp_dir_name_is_renamed(fn, raw):
    out = fn.sanitize_filename(raw)
    assert_safe(out)


def test_alternate_data_stream_colon_is_removed(fn):
    out = fn.sanitize_filename("a.txt:ads")
    assert_safe(out)
    assert ":" not in out
    assert out.startswith("a")


@pytest.mark.parametrize("raw", ["C:x", "C:", "c:\\", "a<b>c.txt", 'a"b".txt', "a|b?c*.txt", "???"])
def test_forbidden_windows_characters_are_removed(fn, raw):
    assert_safe(fn.sanitize_filename(raw))


def test_rtl_override_removed_and_real_extension_kept(fn):
    # "photo‮gpj.exe" hiện ra như "photoexe.jpg": đuôi thật là .exe và phải giữ nguyên là .exe.
    out = fn.sanitize_filename("photo\u202egpj.exe")
    assert_safe(out)
    assert "\u202e" not in out
    assert out.endswith(".exe")


@pytest.mark.parametrize("ch", sorted(INVISIBLE))
def test_invisible_and_bidi_characters_removed(fn, ch):
    out = fn.sanitize_filename(f"a{ch}b.txt")
    assert_safe(out)
    assert out.endswith(".txt")


def test_zero_width_joiner_is_allowed(fn):
    name = "👩\u200d💻.txt"
    assert fn.sanitize_filename(name) == name


@pytest.mark.parametrize(
    "raw",
    ["a\nb.txt", "a\rb.txt", "tab\there.txt", "\x00", "a\x00b", "\x7f.txt", "a\x85b", "\x1b[31mred"],
)
def test_control_characters_removed(fn, raw):
    assert_safe(fn.sanitize_filename(raw))


@pytest.mark.parametrize("raw", ["a\ud800b.txt", "\udcff", "\udcff\udcfe.bin", "x\udfff"])
def test_lone_surrogates_removed(fn, raw):
    out = fn.sanitize_filename(raw)
    assert_safe(out)
    out.encode("utf-8")  # không được ném UnicodeEncodeError


def test_nfd_and_nfc_give_same_nfc_result(fn):
    nfc = "Tiếng Việt – ảnh đẹp.txt"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc
    assert fn.sanitize_filename(nfd) == nfc
    assert fn.sanitize_filename(nfc) == nfc


def test_nfd_form_of_allowed_char_containing_forbidden_base_is_kept(fn):
    # U+226E "≮" hợp lệ; dạng NFD của nó là "<" + U+0338. Chuẩn hóa NFC phải chạy trước khi loại
    # ký tự cấm, nếu không hai dạng của cùng một tên cho hai kết quả khác nhau.
    nfc = "a\u226eb.txt"
    nfd = unicodedata.normalize("NFD", nfc)
    assert "<" in nfd
    assert fn.sanitize_filename(nfd) == fn.sanitize_filename(nfc) == nfc


def _assert_cut_keeping_extension(out: str, stem: str, ext: str) -> None:
    assert utf8_len(out) <= MAX_BYTES
    assert out.endswith(ext)
    kept = out[: len(out) - len(ext)]
    assert stem.startswith(kept), "phần trước đuôi phải là phần đầu của tên gốc (cắt, không đổi)"
    # Cắt theo ký tự, không bỏ phí: thiếu tối đa một ký tự UTF-8 (≤ 3 byte) so với 255.
    assert utf8_len(out) > MAX_BYTES - 4


@pytest.mark.parametrize(
    ("stem", "ext"),
    [
        ("a" * 296, ".txt"),  # 300 byte ASCII
        ("ệ" * 100, ".txt"),  # 304 byte, mỗi ký tự 3 byte
        ("😀" * 75, ".mp4"),  # 304 byte, mỗi ký tự 4 byte
        ("Báo cáo " * 40, ".docx"),
        ("a" * 252, ".txt"),  # 256 byte: vượt đúng 1 byte
    ],
)
def test_long_name_cut_to_255_bytes_keeping_extension(fn, stem, ext):
    raw = stem + ext
    assert utf8_len(raw) > MAX_BYTES
    out = fn.sanitize_filename(raw)
    assert_safe(out)
    _assert_cut_keeping_extension(out, stem, ext)


def test_long_nfd_name_is_normalized_then_cut(fn):
    stem = "ệ" * 100
    raw = unicodedata.normalize("NFD", stem) + ".txt"  # 504 byte ở NFD, 304 byte ở NFC
    out = fn.sanitize_filename(raw)
    assert_safe(out)
    _assert_cut_keeping_extension(out, stem, ".txt")


@pytest.mark.parametrize("raw", ["a" * 251 + ".txt", "ệ" * 85, "😀" * 63 + "abc"])
def test_name_of_exactly_255_bytes_is_unchanged(fn, raw):
    assert utf8_len(raw) == MAX_BYTES
    assert fn.sanitize_filename(raw) == raw


def test_long_cut_does_not_leave_trailing_dot_or_space(fn):
    # Phần cắt rơi đúng vào dấu cách / dấu chấm: kết quả vẫn không được kết thúc bằng chúng.
    for raw in ("a" * 254 + " b", "a" * 254 + ".b" * 30, "a " * 200, "a." * 200):
        assert_safe(fn.sanitize_filename(raw))


def test_very_long_extension_still_fits(fn):
    assert_safe(fn.sanitize_filename("a." + "b" * 400))
    assert_safe(fn.sanitize_filename("." + "b" * 400))


def test_very_long_input_does_not_fail(fn):
    assert_safe(fn.sanitize_filename("x" * 100_000 + ".txt"))
    assert_safe(fn.sanitize_filename("/" * 100_000))
    assert_safe(fn.sanitize_filename("\u202e" * 10_000))


# ---------------------------------------------------------------------------------------------
# sanitize_filename: kiểm trên hệ file thật của máy chạy test
# ---------------------------------------------------------------------------------------------

REAL_FS_CASES = [
    "../../x",
    "..",
    ".",
    "",
    "C:\\Windows\\x",
    "\\\\?\\C:\\x",
    "/etc/passwd",
    "CON",
    "con",
    "NUL.txt",
    "con .txt",
    "COM\u00b9",
    "LPT9.log",
    "a.txt:ads",
    "x.",
    "x ",
    "x.part.state",
    "a.part",
    ".teleport",
    "photo\u202egpj.exe",
    "a\nb.txt",
    "a\ud800b.txt",
    "COM0",
    "LPT0",
    "CONIN$",
    "CONOUT$",
    "CLOCK$",
]


def _create_in(directory: str, name: str) -> list[str]:
    with open(os.path.join(directory, name), "xb") as f:
        f.write(b"x")
    return os.listdir(directory)


@pytest.mark.parametrize("raw", REAL_FS_CASES)
def test_sanitized_name_creates_exactly_that_file_in_receive_dir(fn, tmp_path, raw):
    """File tạo bằng tên đã làm sạch nằm đúng trong thư mục nhận, đúng tên đó, là file thường.

    Bắt cả những gì hệ điều hành tự làm với tên (Windows cắt dấu chấm cuối, mở ADS sau `:`,
    mở thiết bị thay vì file) mà danh sách luật ở trên có thể bỏ sót.
    """
    recv = tmp_path / "recv"
    recv.mkdir()
    out = fn.sanitize_filename(raw)
    listed = _create_in(str(recv), out)
    assert [unicodedata.normalize("NFC", n) for n in listed] == [out]
    assert (recv / out).is_file()
    assert (recv / out).read_bytes() == b"x"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["recv"]


# ---------------------------------------------------------------------------------------------
# sanitize_filename: thuộc tính (hypothesis)
# ---------------------------------------------------------------------------------------------

# Mọi code point, kể cả surrogate lẻ (Cs).
ANY_CHAR = st.characters(exclude_categories=())

TRICKY_PIECES = st.sampled_from(
    [
        "/",
        "\\",
        ":",
        "..",
        ".",
        " ",
        "  ",
        "C:",
        "\\\\?\\",
        "CON",
        "con",
        "nul",
        "Com1",
        "LPT\u00b9",
        "COM\u00b3",
        ".txt",
        ".teleport",
        ".TELEPORT",
        "\u202e",
        "\u2066",
        "\u200b",
        "\ufeff",
        "\u200d",
        "\x00",
        "\n",
        "\x7f",
        "\x85",
        "\ud800",
        "\udfff",
        "e\u0301",
        "é",
        "\u226e",
        "<\u0338",
        "ệ",
        "😀",
        "\u0958",  # NFC tách thành 2 code point (loại trừ khỏi hợp tự): dài thêm khi chuẩn hóa
        "\u0f73",
        "\u1100\u1161",  # Hangul ghép
        "a",
        "Z",
        "\u00df",
        "\u0130",
    ]
)

NAMES = st.one_of(
    st.text(ANY_CHAR, max_size=80),
    st.lists(st.one_of(ANY_CHAR, TRICKY_PIECES), max_size=60).map("".join),
    # Tên dài quanh mốc 255 byte, cắt rơi vào ký tự nhiều byte / dấu kết hợp / dấu chấm, dấu cách.
    st.lists(
        st.sampled_from(["a", "ệ", "😀", "e\u0301", ".", " ", ".txt", "\u0958", "CON", "\u202e"]),
        min_size=50,
        max_size=200,
    ).map("".join),
)

PROPERTY_SETTINGS = settings(max_examples=400, deadline=None)


@pytest.mark.slow
@PROPERTY_SETTINGS
@given(NAMES)
def test_property_sanitized_name_is_always_safe(fn, raw):
    assert_safe(fn.sanitize_filename(raw))


@pytest.mark.slow
@PROPERTY_SETTINGS
@given(NAMES)
def test_property_sanitize_is_idempotent(fn, raw):
    out = fn.sanitize_filename(raw)
    assert fn.sanitize_filename(out) == out


@pytest.mark.slow
@PROPERTY_SETTINGS
@given(NAMES)
def test_property_nfd_and_nfc_inputs_give_same_result(fn, raw):
    nfc = unicodedata.normalize("NFC", raw)
    nfd = unicodedata.normalize("NFD", raw)
    assert fn.sanitize_filename(nfd) == fn.sanitize_filename(nfc)


@pytest.mark.slow
@PROPERTY_SETTINGS
@given(NAMES)
def test_property_result_is_last_component_only(fn, raw):
    # Thêm thư mục phía trước không đổi kết quả: chỉ phần tên cuối được dùng.
    out = fn.sanitize_filename(raw)
    assert fn.sanitize_filename("../../etc/" + out) == out
    assert fn.sanitize_filename("C:\\Windows\\" + out) == out


@pytest.mark.slow
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.one_of(ANY_CHAR, TRICKY_PIECES), max_size=12).map("".join))
def test_property_sanitized_short_name_creates_that_file_on_real_fs(fn, raw):
    out = fn.sanitize_filename(raw)
    with tempfile.TemporaryDirectory() as d:
        recv = os.path.join(d, "recv")
        os.mkdir(recv)
        try:
            listed = _create_in(recv, out)
        except OSError as e:
            # APFS từ chối (EILSEQ) code point mà bảng Unicode của nó coi là chưa gán (ví dụ U+18DF3);
            # bảng đó có thể cũ hơn bảng của Python, nên `core` không lọc hết được. Lúc tạo file,
            # `app/storage.py` (P2-5) phải xử lý lỗi này. Ở đây chỉ bỏ ví dụ.
            if e.errno != errno.EILSEQ:
                raise
            reject()
        assert [unicodedata.normalize("NFC", n) for n in listed] == [out]
        assert os.listdir(d) == ["recv"]


# ---------------------------------------------------------------------------------------------
# numbered
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "n", "expected"),
    [
        ("a.txt", 1, "a (1).txt"),
        ("a.txt", 2, "a (2).txt"),
        ("a", 2, "a (2)"),
        ("file", 1, "file (1)"),
        ("Báo cáo.docx", 10, "Báo cáo (10).docx"),
        ("a b.txt", 3, "a b (3).txt"),
    ],
)
def test_numbered_puts_suffix_before_extension(fn, name, n, expected):
    assert fn.numbered(name, n) == expected


def test_numbered_multi_dot_name_keeps_last_extension(fn):
    out = fn.numbered("a.tar.gz", 1)
    assert " (1)" in out
    assert out.endswith(".gz")
    assert_safe(out)


@pytest.mark.parametrize("n", [1, 9, 10, 99, 12345, 10**9, 10**15])
@pytest.mark.parametrize(
    ("stem", "ext"),
    [
        ("a" * 251, ".txt"),  # đúng 255 byte
        ("ệ" * 83, ".txt"),  # 253 byte
        ("😀" * 62, ".mp4"),  # 252 byte
        ("x" * 255, ""),
    ],
)
def test_numbered_near_limit_fits_and_keeps_extension(fn, stem, ext, n):
    name = stem + ext
    assert utf8_len(name) <= MAX_BYTES
    out = fn.numbered(name, n)
    suffix = f" ({n}){ext}"
    assert utf8_len(out) <= MAX_BYTES
    assert out.endswith(suffix)
    assert stem.startswith(out[: len(out) - len(suffix)])
    assert_safe(out)
    assert fn.sanitize_filename(out) == out


@pytest.mark.parametrize("max_bytes", [32, 64, 100])
def test_numbered_respects_custom_max_bytes(fn, max_bytes):
    out = fn.numbered("ệ" * 50 + ".txt", 7, max_bytes=max_bytes)
    assert utf8_len(out) <= max_bytes
    assert out.endswith(" (7).txt")


def test_numbered_with_huge_extension_still_fits(fn):
    name = "a." + "b" * 252  # 255 byte, đuôi 253 byte
    out = fn.numbered(name, 1)
    assert utf8_len(out) <= MAX_BYTES
    assert key(out) != key(name)
    assert fn.sanitize_filename(out) == out
    assert_safe(out)


def test_numbered_device_like_and_dotfile_stay_safe(fn):
    for name in [fn.sanitize_filename("CON"), fn.sanitize_filename(".teleport"), ".bashrc"]:
        out = fn.numbered(name, 1)
        assert_safe(out)
        assert key(out) != key(name)


@pytest.mark.slow
@PROPERTY_SETTINGS
@given(NAMES, st.integers(min_value=1, max_value=10**12))
def test_property_numbered_is_safe_and_distinct(fn, raw, n):
    name = fn.sanitize_filename(raw)
    out = fn.numbered(name, n)
    assert utf8_len(out) <= MAX_BYTES
    assert f"({n})" in out
    assert_safe(out)
    assert fn.sanitize_filename(out) == out
    assert key(out) != key(name)
    assert key(fn.numbered(name, n + 1)) != key(out)


@pytest.mark.slow
@PROPERTY_SETTINGS
@given(NAMES, st.integers(min_value=1, max_value=10**6), st.integers(min_value=40, max_value=255))
def test_property_numbered_respects_max_bytes(fn, raw, n, max_bytes):
    out = fn.numbered(fn.sanitize_filename(raw), n, max_bytes=max_bytes)
    assert utf8_len(out) <= max_bytes
    assert f"({n})" in out


# ---------------------------------------------------------------------------------------------
# dedupe_offer_names
# ---------------------------------------------------------------------------------------------


def _assert_dedupe_contract(fn, names: list[str], out: list[str]) -> None:
    """Hợp đồng chung của `dedupe_offer_names` (kế hoạch mục 4, protocol mục 4.4)."""
    assert isinstance(out, list)
    assert len(out) == len(names)
    keys = [key(o) for o in out]
    assert len(set(keys)) == len(keys), "các tên kết quả phải khác nhau theo casefold"
    clean = [fn.sanitize_filename(n) for n in names]
    seen: set[str] = set()
    # Tập tên đánh số dựng một lần cho mỗi tên đã làm sạch: dựng lại cho từng bản là O(n²), riêng ca
    # 1000 tên trùng đã mất hàng chục giây.
    numbered: dict[str, set[str]] = {}
    for i, (o, c) in enumerate(zip(out, clean, strict=True)):
        assert_safe(o)
        if key(c) not in seen:
            # Bản đầu tiên của mỗi tên giữ đúng tên đã làm sạch (kể cả khi một bản đánh số trước
            # đó có thể đã muốn lấy tên này).
            assert o == c, (i, names, out)
        else:
            # Bản sau: tên đã làm sạch kèm ` (k)`; mỗi tên khác chặn tối đa một số k.
            if c not in numbered:
                numbered[c] = {fn.numbered(c, k) for k in range(1, len(names) + 2)}
            assert o in numbered[c], (i, names, out)
        seen.add(key(c))


def test_dedupe_empty_list(fn):
    assert fn.dedupe_offer_names([]) == []


def test_dedupe_distinct_names_unchanged(fn):
    names = ["a.txt", "b.txt", "Báo cáo.docx", "x.part.state"]
    assert fn.dedupe_offer_names(names) == names


def test_dedupe_case_insensitive_duplicates_are_numbered(fn):
    names = ["a.txt", "A.TXT", "a.txt"]
    out = fn.dedupe_offer_names(names)
    assert out[0] == "a.txt"
    assert len({key(o) for o in out}) == 3
    _assert_dedupe_contract(fn, names, out)


def test_dedupe_nfd_and_nfc_are_duplicates(fn):
    nfc = "Tiếng Việt.txt"
    nfd = unicodedata.normalize("NFD", nfc)
    names = [nfd, nfc]
    out = fn.dedupe_offer_names(names)
    assert out[0] == nfc
    assert key(out[1]) != key(nfc)
    _assert_dedupe_contract(fn, names, out)


def test_dedupe_casefold_not_just_lower(fn):
    # casefold("ß") == "ss": "Straße.txt" và "STRASSE.txt" coi là trùng.
    names = ["Straße.txt", "STRASSE.txt"]
    out = fn.dedupe_offer_names(names)
    assert key(out[0]) != key(out[1])
    _assert_dedupe_contract(fn, names, out)


def test_dedupe_numbered_name_avoids_existing_later_name(fn):
    # Có sẵn `a (1).txt` ở sau: bản trùng của `a.txt` không được lấy tên đó, và `a (1).txt` giữ tên.
    names = ["a.txt", "a.txt", "a (1).txt"]
    out = fn.dedupe_offer_names(names)
    assert out[0] == "a.txt"
    assert out[2] == "a (1).txt"
    assert key(out[1]) not in {key("a.txt"), key("a (1).txt")}
    _assert_dedupe_contract(fn, names, out)


def test_dedupe_numbered_name_avoids_existing_earlier_name(fn):
    names = ["a (1).txt", "A (1).TXT", "a.txt", "a.txt"]
    out = fn.dedupe_offer_names(names)
    assert out[0] == "a (1).txt"
    assert out[2] == "a.txt"
    _assert_dedupe_contract(fn, names, out)


def test_dedupe_names_equal_only_after_sanitizing(fn):
    names = ["dir1/a.txt", "dir2\\a.txt", "a.txt.", "a.txt ", "", ".", "file", "CON", "con"]
    out = fn.dedupe_offer_names(names)
    _assert_dedupe_contract(fn, names, out)


def test_dedupe_long_duplicates_stay_within_limit(fn):
    names = ["x" * 251 + ".txt"] * 12
    out = fn.dedupe_offer_names(names)
    _assert_dedupe_contract(fn, names, out)
    assert all(o.endswith(".txt") for o in out)


def test_dedupe_thousand_identical_names(fn):
    # Một `offer` có tới 1000 file (kế hoạch mục 6e).
    names = ["a.txt"] * 1000
    out = fn.dedupe_offer_names(names)
    _assert_dedupe_contract(fn, names, out)


def test_dedupe_does_not_mutate_input(fn):
    names = ["a.txt", "A.txt"]
    fn.dedupe_offer_names(names)
    assert names == ["a.txt", "A.txt"]


DEDUPE_POOL = st.sampled_from(
    [
        "a.txt",
        "A.TXT",
        "a (1).txt",
        "A (1).TXT",
        "a (2).txt",
        "a (1) (1).txt",
        "a",
        "a (1)",
        "CON",
        "con.txt",
        "",
        ".",
        "file",
        "file (1)",
        "Tiếng.txt",
        unicodedata.normalize("NFD", "Tiếng.txt"),
        "x" * 251 + ".txt",
        "X" * 251 + ".TXT",
        "ß.txt",
        "SS.txt",
        "a.txt:x",
        "a.txt?x",
        "a.txt.",
        ".teleport",
    ]
)


@pytest.mark.slow
@settings(max_examples=300, deadline=None)
@given(st.lists(st.one_of(DEDUPE_POOL, NAMES), max_size=30))
def test_property_dedupe_contract(fn, names):
    out = fn.dedupe_offer_names(names)
    _assert_dedupe_contract(fn, names, out)


def _reference_dedupe(fn, names: list[str]) -> list[str]:
    """Thuật toán khử trùng cũ (trước bản sửa bậc hai), làm tham chiếu.

    `restore` chạy lại `dedupe_offer_names` cho lượt đã lưu, nên bản mới phải cho đúng kết quả
    này với mọi đầu vào. Bộ đếm nhớ theo khóa của tên gốc, nên số được chọn không phải lúc nào
    cũng là số nhỏ nhất còn trống (hai tên cùng khóa nhưng dài khác nhau bị cắt khác nhau).
    """
    cleaned = [fn.sanitize_filename(name) for name in names]
    keys = [fn.dedupe_key(name) for name in cleaned]
    taken = set(keys)
    seen: set[str] = set()
    next_number: dict[str, int] = {}
    result: list[str] = []
    for name, k in zip(cleaned, keys, strict=True):
        if k not in seen:
            seen.add(k)
            result.append(name)
            continue
        n = next_number.get(k, 1)
        while True:
            candidate = fn.numbered(name, n)
            n += 1
            candidate_key = fn.dedupe_key(candidate)
            if candidate_key not in taken:
                break
        next_number[k] = n
        taken.add(candidate_key)
        result.append(candidate)
    return result


def _long_name(prefix: str, tail: str, ext: str) -> str:
    """Tên đúng 255 byte: `prefix` lặp cho đủ chỗ, rồi `tail` và `ext`."""
    room = MAX_BYTES - utf8_len(tail) - utf8_len(ext)
    body = (prefix * room).encode("utf-8")[:room].decode("utf-8", "ignore")
    body += "a" * (room - utf8_len(body))
    return body + tail + ext


# Tên dài 255 byte khác nhau ở cuối thân (bị cắt khi đánh số), tên trùng hoa thường, tên kiểu
# `a (1).txt`, tên không đuôi, tên có số nhiều chữ số sẵn.
REFERENCE_POOL = st.one_of(
    DEDUPE_POOL,
    st.builds(
        _long_name,
        # `ﬁ`/`FI`, `ẞ`/`ß`/`SS`, `İ`: casefold đổi độ dài byte, nên hai tên cùng khóa bị cắt
        # khác nhau khi đánh số.
        st.sampled_from(["a", "A", "ệ", "😀", "ﬁ", "FI", "ẞ", "ß", "SS", "İ"]),
        st.sampled_from(["", "1", "2", "12", "x", "X", " (1)", " (10)"]),
        st.sampled_from(["", ".txt", ".TXT", ".mp4"]),
    ),
    st.builds(
        "{}{}{}".format,
        st.sampled_from(["a", "A", "b", "file", "CON"]),
        st.sampled_from(["", " (1)", " (2)", " (9)", " (10)", " (11)", " (100)"]),
        st.sampled_from(["", ".txt", ".TXT"]),
    ),
)


@pytest.mark.slow
@settings(max_examples=300, deadline=None)
@given(st.lists(st.one_of(REFERENCE_POOL, NAMES), max_size=40))
def test_property_dedupe_matches_reference(fn, names):
    assert fn.dedupe_offer_names(names) == _reference_dedupe(fn, names)


@pytest.mark.parametrize(
    "names",
    [
        ["a.txt"] * 25 + ["a (1).txt", "a (10).txt", "A (11).TXT"],
        ["a"] * 120,
        [_long_name("a", d, ".txt") for d in ("1", "2", "3") for _ in range(6)],
        [_long_name("a", f"{i:02d}", "") for i in range(15) for _ in range(2)],
        # Cùng khóa, khác độ dài byte (255 và 254): bản cũ nhớ số theo khóa tên gốc nên B lấy
        # ` (2)` dù tên đánh số của B với ` (1)` khác khóa với của A.
        ["ﬁ" + "a" * 248 + ".txt"] * 2 + ["FI" + "a" * 248 + ".txt"],
    ],
)
def test_dedupe_matches_reference_across_digit_bands(fn, names):
    assert fn.dedupe_offer_names(names) == _reference_dedupe(fn, names)


def test_dedupe_long_names_cut_to_same_prefix_is_fast(fn):
    # 500 cặp tên 255 byte khác nhau ở 10 chữ số cuối thân: khi đánh số, `_fit` cắt mất phần
    # khác nhau nên mọi bản trùng giành cùng một dãy tên. Bản cũ bậc hai mất vài giây.
    names = ["a" * 241 + f"{i:010d}" + ".txt" for i in range(500) for _ in range(2)]
    start = time.perf_counter()
    out = fn.dedupe_offer_names(names)
    elapsed = time.perf_counter() - start
    assert len({key(o) for o in out}) == len(names)
    assert elapsed < 0.5, f"{elapsed:.2f} s"


# ---------------------------------------------------------------------------------------------
# prepare_outgoing_name (bên gửi)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "a.txt",
        "Báo cáo tháng 10.docx",
        "ảnh 🎉.jpg",
        "a" * 251 + ".txt",  # đúng 255 byte
        # Hợp lệ trên máy gửi (macOS/Linux) dù Windows cấm: việc làm sạch là của bên nhận.
        "a:b.txt",
        "CON",
        "x.",
        "a\\b.txt",
        "photo\u202egpj.exe",  # Cf, không phải Cc
    ],
)
def test_outgoing_name_kept_when_valid(fn, name):
    assert fn.prepare_outgoing_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "bao\ncao.txt",
        "a\rb",
        "a\tb.txt",
        "\x00",
        "a\x1fb",
        "a\x7fb",  # DEL là Cc
        "a\x85b",  # NEL (C1) là Cc
        "a\x9fb",
    ],
)
def test_outgoing_name_with_control_char_rejected(fn, name):
    with pytest.raises(fn.OutgoingNameError):
        fn.prepare_outgoing_name(name)


@pytest.mark.parametrize("name", ["a\ud800b.txt", "\udcff", "x\udfff.bin"])
def test_outgoing_name_with_lone_surrogate_rejected(fn, name):
    with pytest.raises(fn.OutgoingNameError):
        fn.prepare_outgoing_name(name)


def test_outgoing_error_is_exception(fn):
    assert issubclass(fn.OutgoingNameError, Exception)


@pytest.mark.parametrize(
    ("stem", "ext"),
    [
        ("a" * 296, ".txt"),
        ("a" * 252, ".txt"),  # 256 byte: vượt đúng 1 byte
        ("ệ" * 100, ".txt"),
        ("😀" * 75, ".mp4"),
    ],
)
def test_outgoing_long_name_cut_keeping_extension(fn, stem, ext):
    out = fn.prepare_outgoing_name(stem + ext)
    _assert_cut_keeping_extension(out, stem, ext)


def test_outgoing_long_name_without_extension_is_cut(fn):
    stem = "ệ" * 100
    out = fn.prepare_outgoing_name(stem)
    assert utf8_len(out) <= MAX_BYTES
    assert stem.startswith(out)
    assert utf8_len(out) > MAX_BYTES - 4


# Mọi chuỗi không có Cc/Cs: không ném, ≤ 255 byte, và giữ nguyên nếu vốn ≤ 255 byte.
OUTGOING_OK = st.text(st.characters(exclude_categories=("Cc", "Cs")), min_size=1, max_size=300) | st.lists(
    st.sampled_from(["a", "ệ", "😀", "e\u0301", ".", " ", ".txt"]), min_size=1, max_size=200
).map("".join)


@PROPERTY_SETTINGS
@given(OUTGOING_OK)
def test_property_outgoing_valid_name(fn, name):
    out = fn.prepare_outgoing_name(name)
    assert isinstance(out, str)
    assert utf8_len(out) <= MAX_BYTES
    assert not [c for c in out if unicodedata.category(c) in ("Cc", "Cs")]
    if utf8_len(name) <= MAX_BYTES:
        # Đặc tả không nói bên gửi có chuẩn hóa NFC hay không: chỉ đòi không đổi nội dung.
        assert unicodedata.normalize("NFC", out) == unicodedata.normalize("NFC", name)


@PROPERTY_SETTINGS
@given(
    st.text(max_size=40),
    st.characters(categories=("Cc", "Cs")),
    st.text(max_size=40),
)
def test_property_outgoing_rejects_any_cc_or_cs(fn, before, bad, after):
    with pytest.raises(fn.OutgoingNameError):
        fn.prepare_outgoing_name(before + bad + after)
