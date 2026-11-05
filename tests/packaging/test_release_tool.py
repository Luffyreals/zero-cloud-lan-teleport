"""Test đơn vị cho các bước kiểm của workflow phát hành (`packaging/release/release.py`).

Đặc tả: `docs/CONTRIBUTING.md` mục “Phát hành” (luật hai dạng số: tag SemVer `v0.1.0-alpha` ↔ PEP 440
`0.1.0a0`, beta `-beta` ↔ `b0`, bản thường hai dạng bằng nhau; rc, `a1`, `.dev`, `.post` không phát hành
được) và docstring của `release.py` (mục CHANGELOG `## [<số SemVer>] - YYYY-MM-DD`, `fetch-sources` kiểm
SHA-256 và bản ghim, lỗi thì thoát mã 1).

Script không phải gói nên nạp bằng `importlib.util.spec_from_file_location` (như `test_third_party.py`;
`import packaging…` trùng gói PyPI). Không test nào mở mạng: `urlopen` bị thay, `__version__`,
`CHANGELOG.md` và `constraints.txt` giả nằm trong `tmp_path` (thay các hằng đường dẫn của module).
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from hypothesis import given
from hypothesis import strategies as st

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "packaging" / "release" / "release.py"


def _load_release() -> ModuleType:
    name = "teleport_packaging_release_under_test"
    saved_path = list(sys.path)
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved_path  # script tự thêm packaging/pyinstaller vào sys.path để import third_party
    return module


rel = _load_release()
ReleaseError = rel.ReleaseError
tp = rel.third_party

_TAG_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(a0|b0)?")


def _reference_tag(version: str) -> str | None:
    """Tag mong đợi theo luật của CONTRIBUTING.md, viết độc lập với code; ngoài luật thì None."""
    match = _TAG_RE.fullmatch(version)
    if match is None:
        return None
    major, minor, patch, pre = match.groups()
    suffix = {"a0": "-alpha", "b0": "-beta", None: ""}[pre]
    return f"v{major}.{minor}.{patch}{suffix}"


# ---------------------------------------------------------------- fixture


@pytest.fixture
def fake_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Ghi `__version__` giả và trỏ `rel.INIT` tới đó; trả hàm đặt phiên bản."""
    init = tmp_path / "__init__.py"

    def set_version(version: str) -> None:
        init.write_text(f'"""App giả."""\n\n__version__ = {version!r}\n', encoding="utf-8")

    monkeypatch.setattr(rel, "INIT", init)
    set_version("0.1.0a0")
    return set_version


@pytest.fixture
def fake_changelog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "CHANGELOG.md"
    monkeypatch.setattr(rel, "CHANGELOG", path)

    def write(text: str) -> Path:
        path.write_text(text, encoding="utf-8")
        return path

    return write


# ---------------------------------------------------------------- ánh xạ phiên bản → tag


@pytest.mark.parametrize(
    ("version", "tag"),
    [
        ("0.1.0a0", "v0.1.0-alpha"),
        ("0.3.0b0", "v0.3.0-beta"),
        ("1.0.0", "v1.0.0"),
        ("0.0.0", "v0.0.0"),
        ("10.20.30", "v10.20.30"),
        ("2.0.0a0", "v2.0.0-alpha"),
    ],
)
def test_tag_for_version_follows_two_form_rule(version: str, tag: str) -> None:
    assert rel.tag_for_version(version) == tag


@pytest.mark.parametrize(
    "version",
    [
        "0.1.0rc1",
        "0.1.0rc0",
        "0.1.0a1",
        "0.1.0b1",
        "0.1.0a00",
        "0.1.0c0",
        "0.1.0.dev0",
        "0.1.0a0.dev0",
        "1.0.0.post1",
        "1.0.0.post0",
        "1.0.0+local",
        "0.1.0a0+abc",
        "01.0.0",
        "1.00.0",
        "1.0.01",
        "0.1.0-alpha",  # dạng SemVer trong __version__: chưa chuẩn hóa PEP 440
        "0.1.0alpha0",
        "0.1.0A0",
        "v1.0.0",
        "1.0",
        "1",
        "1.0.0.0",
        "",
        " 1.0.0",
        "1.0.0 ",
        "1.0.0\n",
        "1.0.٠",  # chữ số Ả Rập: không phải chữ số ASCII
        "1٠.0.0",
        "1.2٣.0",
    ],
)
def test_tag_for_version_rejects_forms_outside_rule(version: str) -> None:
    with pytest.raises(ReleaseError):
        rel.tag_for_version(version)


@given(
    major=st.integers(0, 999),
    minor=st.integers(0, 999),
    patch=st.integers(0, 999),
    pre=st.sampled_from(["", "a0", "b0"]),
)
def test_tag_for_version_matches_reference_and_check_tag_accepts_it(
    major: int, minor: int, patch: int, pre: str
) -> None:
    version = f"{major}.{minor}.{patch}{pre}"
    tag = rel.tag_for_version(version)
    assert tag == _reference_tag(version)
    rel.check_tag(tag, version)  # không lỗi
    assert rel.is_prerelease(version) is (pre != "")


@given(st.text(alphabet="0123456789.abrcdevpost+-", max_size=14))
def test_tag_for_version_accepts_exactly_the_reference_set(version: str) -> None:
    expected = _reference_tag(version)
    if expected is None:
        with pytest.raises(ReleaseError):
            rel.tag_for_version(version)
    else:
        assert rel.tag_for_version(version) == expected


@pytest.mark.parametrize(("version", "pre"), [("0.1.0a0", True), ("0.3.0b0", True), ("1.0.0", False)])
def test_is_prerelease_true_only_for_alpha_and_beta(version: str, pre: bool) -> None:
    assert rel.is_prerelease(version) is pre


def test_is_prerelease_rejects_forms_outside_rule() -> None:
    with pytest.raises(ReleaseError):
        rel.is_prerelease("0.1.0rc1")


# ---------------------------------------------------------------- check-tag


@pytest.mark.parametrize(
    ("tag", "version"), [("v0.1.0-alpha", "0.1.0a0"), ("v0.3.0-beta", "0.3.0b0"), ("v1.0.0", "1.0.0")]
)
def test_check_tag_accepts_matching_tag(tag: str, version: str) -> None:
    rel.check_tag(tag, version)


@pytest.mark.parametrize(
    ("tag", "version"),
    [
        ("v0.1.0a0", "0.1.0a0"),  # tag theo dạng PEP 440
        ("0.1.0-alpha", "0.1.0a0"),  # thiếu v
        ("V0.1.0-alpha", "0.1.0a0"),
        ("v0.1.0-Alpha", "0.1.0a0"),
        ("v0.1.0-beta", "0.1.0a0"),
        ("v0.1.0", "0.1.0a0"),
        ("v0.1.0-alpha", "0.1.0"),
        ("v0.1.0-alpha.1", "0.1.0a0"),
        ("v0.1.0-alpha ", "0.1.0a0"),
        ("v0.1.1-alpha", "0.1.0a0"),
        ("v1.0.0", "1.0.0.post1"),
        ("v0.1.0-rc", "0.1.0rc1"),
        ("", "1.0.0"),
    ],
)
def test_check_tag_rejects_tag_that_does_not_match_version(tag: str, version: str) -> None:
    with pytest.raises(ReleaseError):
        rel.check_tag(tag, version)


def test_main_check_tag_exits_0_on_match(fake_version, capsys: pytest.CaptureFixture[str]) -> None:
    fake_version("0.3.0b0")
    assert rel.main(["check-tag", "v0.3.0-beta"]) == 0


@pytest.mark.parametrize("tag", ["v0.3.0-alpha", "v0.3.0", "v0.3.0b0", "v0.3.0-beta; rm -rf /"])
def test_main_check_tag_exits_1_with_reason_on_mismatch(
    fake_version, capsys: pytest.CaptureFixture[str], tag: str
) -> None:
    fake_version("0.3.0b0")
    assert rel.main(["check-tag", tag]) == 1
    assert capsys.readouterr().err.strip()


@pytest.mark.parametrize(
    "version", ["0.1.0rc1", "0.1.0a1", "0.1.0.dev0", "1.0.0.post1", "1.0.0+local", "01.0.0"]
)
def test_main_check_tag_exits_1_when_version_cannot_be_released(
    fake_version, capsys: pytest.CaptureFixture[str], version: str
) -> None:
    fake_version(version)
    tag = "v" + version  # tag nào cũng không cứu được
    assert rel.main(["check-tag", tag]) == 1
    assert capsys.readouterr().err.strip()


def test_main_exits_1_when_init_has_no_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    init = tmp_path / "__init__.py"
    init.write_text('"""Không có phiên bản."""\n', encoding="utf-8")
    monkeypatch.setattr(rel, "INIT", init)
    assert rel.main(["check-tag", "v0.1.0-alpha"]) == 1
    assert capsys.readouterr().err.strip()


def test_main_info_prints_outputs_for_github(fake_version, capsys: pytest.CaptureFixture[str]) -> None:
    fake_version("0.1.0a0")
    assert rel.main(["info"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "version=0.1.0a0" in lines
    assert "tag=v0.1.0-alpha" in lines
    assert "prerelease=true" in lines


def test_main_info_marks_final_release_not_prerelease(
    fake_version, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_version("1.0.0")
    assert rel.main(["info"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "tag=v1.0.0" in lines
    assert "prerelease=false" in lines


def test_script_exit_codes_against_real_version() -> None:
    """Chạy đúng như workflow (tiến trình con, thư viện chuẩn): tag khớp → 0, tag sai → 1."""
    real_version = re.search(
        r'^__version__ = "([^"]+)"',
        (_REPO / "src" / "teleport" / "__init__.py").read_text(encoding="utf-8"),
        re.M,
    )
    assert real_version is not None
    tag = _reference_tag(real_version.group(1))
    if tag is None:
        pytest.skip(f"__version__ {real_version.group(1)} hiện chưa phải dạng phát hành được")

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", str(_SCRIPT), *args],
            cwd=_REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )

    ok = run("check-tag", tag)
    assert ok.returncode == 0, ok.stderr
    bad = run("check-tag", tag + "x")
    assert bad.returncode == 1
    assert bad.stderr.strip()


# ---------------------------------------------------------------- mục CHANGELOG

_CHANGELOG = """\
# Changelog

Mọi thay đổi đáng chú ý.

## [Unreleased]

### Added
- Việc chưa phát hành.

## [0.2.0-beta] - 2026-12-01

### Fixed
- Sửa lỗi beta.

## [0.1.0-alpha] - 2026-11-05

### Added
- Bản thử nghiệm đầu tiên.
- Dòng thứ hai.

### Fixed
- Sửa một lỗi.

## [0.1.0] - 2026-10-01

- Bản thường cũ.
"""


def test_changelog_section_returns_body_until_next_level2_heading() -> None:
    body = rel.changelog_section("v0.1.0-alpha", _CHANGELOG)
    assert body is not None
    assert "Bản thử nghiệm đầu tiên." in body
    assert "### Fixed" in body  # tiêu đề cấp 3 nằm trong mục
    assert "Sửa một lỗi." in body
    assert "Bản thường cũ." not in body
    assert "Sửa lỗi beta." not in body
    assert "Việc chưa phát hành." not in body
    assert "## [0.1.0-alpha]" not in body


def test_changelog_section_of_final_release_does_not_match_prerelease_heading() -> None:
    body = rel.changelog_section("v0.1.0", _CHANGELOG)
    assert body is not None
    assert body.strip() == "- Bản thường cũ."


def test_changelog_section_last_in_file_runs_to_end() -> None:
    body = rel.changelog_section("v0.1.0", _CHANGELOG)
    assert body == "- Bản thường cũ."


def test_changelog_section_missing_returns_none() -> None:
    assert rel.changelog_section("v0.4.0-alpha", _CHANGELOG) is None


@pytest.mark.parametrize(
    "heading",
    [
        "## [0.1.0-alpha]",  # thiếu ngày
        "## [0.1.0-alpha] - 05/11/2026",
        "## [0.1.0-alpha] 2026-11-05",
        "### [0.1.0-alpha] - 2026-11-05",
        "## 0.1.0-alpha - 2026-11-05",
        "## [0.1.0-alpha.1] - 2026-11-05",
        "## [0x1x0-alpha] - 2026-11-05",
        "## [v0.1.0-alpha] - 2026-11-05",
    ],
)
def test_changelog_section_ignores_heading_not_in_spec_form(heading: str) -> None:
    text = f"# Changelog\n\n{heading}\n\n- Nội dung.\n"
    assert rel.changelog_section("v0.1.0-alpha", text) is None


@pytest.mark.parametrize(
    "text",
    [
        "## [0.1.0-alpha] - 2026-11-05\n## [0.0.9] - 2026-10-01\n- cũ\n",
        "## [0.1.0-alpha] - 2026-11-05\n\n   \n\n## [0.0.9] - 2026-10-01\n- cũ\n",
        "# Changelog\n\n## [0.1.0-alpha] - 2026-11-05\n",
        "# Changelog\n\n## [0.1.0-alpha] - 2026-11-05\n\n\n",
    ],
)
def test_changelog_empty_section_counts_as_missing(text: str) -> None:
    assert rel.changelog_section("v0.1.0-alpha", text) is None


def test_changelog_section_handles_crlf() -> None:
    body = rel.changelog_section("v0.1.0-alpha", _CHANGELOG.replace("\n", "\r\n"))
    assert body is not None
    assert "Bản thử nghiệm đầu tiên." in body
    assert "\r" not in body.replace("\r\n", "")
    assert "Bản thường cũ." not in body


def test_release_notes_have_section_and_fixed_lines(fake_changelog) -> None:
    fake_changelog(_CHANGELOG)
    notes = rel.release_notes("v0.1.0-alpha", "0.1.0a0")
    assert notes.startswith("### Added\n- Bản thử nghiệm đầu tiên.")
    # Các dòng cố định theo CONTRIBUTING.md: chưa ký mã (SmartScreen), DOC-TRUOC.txt, SHA-256.
    assert "SmartScreen" in notes
    assert "“More info” → “Run anyway”" in notes
    assert "DOC-TRUOC.txt" in notes
    assert "SHA256SUMS.txt" in notes
    assert "teleport-setup-0.1.0a0-x64.exe" in notes  # tên file phát hành theo dạng PEP 440
    for name, (version, _sha) in tp.LGPL_SDISTS.items():
        assert f"{name}-{version}.tar.gz" in notes


def test_release_notes_missing_section_stops(fake_changelog) -> None:
    fake_changelog(_CHANGELOG)
    with pytest.raises(ReleaseError):
        rel.release_notes("v0.4.0-alpha", "0.4.0a0")


def test_release_notes_empty_section_stops(fake_changelog) -> None:
    fake_changelog("# Changelog\n\n## [0.1.0-alpha] - 2026-11-05\n\n## [0.0.9] - 2026-10-01\n- cũ\n")
    with pytest.raises(ReleaseError):
        rel.release_notes("v0.1.0-alpha", "0.1.0a0")


def test_release_notes_allow_missing_only_writes_dry_run_note(fake_changelog) -> None:
    fake_changelog(_CHANGELOG)
    notes = rel.release_notes("v0.4.0-alpha", "0.4.0a0", allow_missing=True)
    first = notes.split("\n\n", 1)[0]
    assert "0.4.0-alpha" in first
    assert "Bản thử nghiệm đầu tiên." not in notes


def test_main_notes_writes_file_when_section_exists(
    fake_version, fake_changelog, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_version("0.1.0a0")
    fake_changelog(_CHANGELOG)
    out = tmp_path / "notes.md"
    assert rel.main(["notes", "v0.1.0-alpha", "--out", str(out)]) == 0
    assert "Bản thử nghiệm đầu tiên." in out.read_text(encoding="utf-8")


def test_main_notes_missing_section_exits_1_without_file(
    fake_version, fake_changelog, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_version("0.4.0a0")
    fake_changelog(_CHANGELOG)
    out = tmp_path / "notes.md"
    assert rel.main(["notes", "v0.4.0-alpha", "--out", str(out)]) == 1
    assert not out.exists()
    assert capsys.readouterr().err.strip()


def test_main_notes_rejects_tag_not_matching_version(
    fake_version, fake_changelog, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_version("0.2.0b0")
    fake_changelog(_CHANGELOG)
    out = tmp_path / "notes.md"
    assert rel.main(["notes", "v0.1.0-alpha", "--out", str(out)]) == 1
    assert not out.exists()


def test_real_changelog_has_section_for_real_version_tag() -> None:
    """Tài liệu không lệch: khi __version__ là dạng phát hành được, CHANGELOG thật phải có mục của tag."""
    version = rel.app_version()
    tag = _reference_tag(version)
    if tag is None:
        pytest.skip(f"__version__ {version} chưa phải dạng phát hành được")
    text = (_REPO / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert rel.changelog_section(tag, text), f"docs/CHANGELOG.md thiếu mục [{tag[1:]}] - YYYY-MM-DD"


def test_contributing_states_the_two_form_examples() -> None:
    """Các ví dụ của luật trong CONTRIBUTING.md khớp ánh xạ của script."""
    text = (_REPO / "docs" / "CONTRIBUTING.md").read_text(encoding="utf-8")
    section = text.split("## Phát hành", 1)[1].split("\n## ", 1)[0]
    for needle in ("`v0.1.0-alpha`", "`0.1.0a0`", "`0.3.0b0`", "`v1.0.0` ↔ `1.0.0`"):
        assert needle in section
    assert rel.tag_for_version("0.1.0a0") == "v0.1.0-alpha"
    assert rel.tag_for_version("0.3.0b0") == "v0.3.0-beta"
    assert rel.tag_for_version("1.0.0") == "v1.0.0"


# ---------------------------------------------------------------- bản ghim trong constraints.txt


def test_pinned_versions_reads_pins_and_skips_comments() -> None:
    text = (
        "# chú thích zeroconf==9.9.9\n"
        "\n"
        "cryptography==50.0.2\n"
        "zeroconf == 0.151.5  # chú thích cuối dòng\n"
        "PySide6-Essentials==6.12.0\n"
        "Some_Pkg.Name==1.2\n"
        "loose>=1.0\n"
    )
    pins = rel.pinned_versions(text)
    assert pins["cryptography"] == "50.0.2"
    assert pins["zeroconf"] == "0.151.5"
    assert pins["pyside6-essentials"] == "6.12.0"
    assert pins["some-pkg-name"] == "1.2"
    assert "loose" not in pins
    assert "9.9.9" not in pins.values()


def test_pinned_versions_empty_text_gives_no_pins() -> None:
    assert rel.pinned_versions("") == {}


def test_pinned_versions_of_real_constraints_agree_with_lgpl_sdists() -> None:
    """CONTRIBUTING.md: bản trong LGPL_SDISTS phải bằng bản ghim trong constraints.txt (cả hai file thật)."""
    pins = rel.pinned_versions(rel.CONSTRAINTS.read_text(encoding="utf-8"))
    assert "cryptography" in pins and "zeroconf" in pins
    assert tp.LGPL_SDISTS
    for name, (version, _sha) in tp.LGPL_SDISTS.items():
        assert pins.get(name) == version, name


# ---------------------------------------------------------------- fetch-sources

_SDIST = b"sdist gia cua zeroconf\x00\x01" * 100
_VERSION = "0.151.5"


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@pytest.fixture
def fake_pypi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """constraints.txt giả, LGPL_SDISTS giả (hash của `_SDIST`) và `urlopen` giả ghi lại URL đã gọi."""
    constraints = tmp_path / "constraints.txt"
    constraints.write_text(f"# giả\nzeroconf=={_VERSION}\nifaddr==0.2.0\n", encoding="utf-8")
    monkeypatch.setattr(rel, "CONSTRAINTS", constraints)
    monkeypatch.setattr(tp, "LGPL_SDISTS", {"zeroconf": (_VERSION, hashlib.sha256(_SDIST).hexdigest())})
    state: dict[str, object] = {"urls": [], "data": _SDIST}

    def urlopen(url, *args, **kwargs):
        target = url if isinstance(url, str) else url.full_url
        state["urls"].append(target)  # type: ignore[union-attr]
        error = state.get("error")
        if error is not None:
            raise error  # type: ignore[misc]
        return _FakeResponse(state["data"])  # type: ignore[arg-type]

    monkeypatch.setattr(rel.urllib.request, "urlopen", urlopen)
    state["constraints"] = constraints
    return state


def test_fetch_sources_writes_sdist_when_hash_matches(fake_pypi, tmp_path: Path) -> None:
    out = tmp_path / "sources"
    written = rel.fetch_sources(out)
    path = out / f"zeroconf-{_VERSION}.tar.gz"
    assert [Path(p) for p in written] == [path]
    assert path.read_bytes() == _SDIST
    assert fake_pypi["urls"] == [
        f"https://files.pythonhosted.org/packages/source/z/zeroconf/zeroconf-{_VERSION}.tar.gz"
    ]


def test_fetch_sources_wrong_hash_stops_and_leaves_no_file(fake_pypi, tmp_path: Path) -> None:
    fake_pypi["data"] = _SDIST + b"x"  # một byte khác: hash sai
    out = tmp_path / "sources"
    with pytest.raises(ReleaseError):
        rel.fetch_sources(out)
    assert not out.exists() or list(out.iterdir()) == []


def test_fetch_sources_stops_when_constraints_pin_differs(fake_pypi, tmp_path: Path) -> None:
    fake_pypi["constraints"].write_text("zeroconf==0.151.4\n", encoding="utf-8")  # type: ignore[union-attr]
    out = tmp_path / "sources"
    with pytest.raises(ReleaseError):
        rel.fetch_sources(out)
    assert fake_pypi["urls"] == []  # dừng trước khi tải
    assert not out.exists() or list(out.iterdir()) == []


def test_fetch_sources_stops_when_constraints_has_no_pin(fake_pypi, tmp_path: Path) -> None:
    fake_pypi["constraints"].write_text("zeroconf>=0.148\n", encoding="utf-8")  # type: ignore[union-attr]
    with pytest.raises(ReleaseError):
        rel.fetch_sources(tmp_path / "sources")
    assert fake_pypi["urls"] == []


def test_main_fetch_sources_exits_0_on_success(fake_pypi, fake_version, tmp_path: Path) -> None:
    out = tmp_path / "sources"
    assert rel.main(["fetch-sources", "--out", str(out)]) == 0
    assert (out / f"zeroconf-{_VERSION}.tar.gz").read_bytes() == _SDIST


def test_main_fetch_sources_wrong_hash_exits_1_without_file(
    fake_pypi, fake_version, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_pypi["data"] = b""
    out = tmp_path / "sources"
    assert rel.main(["fetch-sources", "--out", str(out)]) == 1
    assert not out.exists() or list(out.iterdir()) == []
    assert capsys.readouterr().err.strip()


def test_main_fetch_sources_network_error_exits_1_without_file(
    fake_pypi, fake_version, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import urllib.error

    fake_pypi["error"] = urllib.error.URLError("mạng hỏng")
    out = tmp_path / "sources"
    assert rel.main(["fetch-sources", "--out", str(out)]) == 1
    assert not out.exists() or list(out.iterdir()) == []
    assert capsys.readouterr().err.strip()
