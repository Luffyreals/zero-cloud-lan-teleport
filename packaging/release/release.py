"""Các bước kiểm và chuẩn bị của workflow phát hành `.github/workflows/release.yml`.

Chạy từ gốc repo, chỉ cần thư viện chuẩn của Python (không cài gói, không import `teleport`):

    python packaging/release/release.py info          # version=, tag=, prerelease= (cho GITHUB_OUTPUT)
    python packaging/release/release.py check-tag v0.1.0-alpha   # dừng nếu tag không khớp __version__
    python packaging/release/release.py notes v0.1.0-alpha --out notes.md [--allow-missing]
    python packaging/release/release.py fetch-sources --out sources/

- Phiên bản chỉ lấy từ `__version__` trong `src/teleport/__init__.py` (đọc bằng `ast`). Luật hai dạng số
  (tag SemVer `v0.1.0-alpha` ↔ PEP 440 `0.1.0a0`, beta `-beta` ↔ `b0`, bản thường bằng nhau) ở
  `docs/CONTRIBUTING.md`, mục “Phát hành”; dạng nào ngoài luật đó (rc, a1, dev, post, local) đều bị từ chối.
- `notes`: nội dung Release là mục `## [<số SemVer>] - YYYY-MM-DD` của `docs/CHANGELOG.md`, cộng các dòng
  cố định ở `FIXED_NOTES`. Không có mục đó thì dừng (`--allow-missing` chỉ dành cho chạy khô).
- `fetch-sources`: tải sdist của thư viện LGPL (`LGPL_SDISTS` trong `packaging/pyinstaller/third_party.py`)
  từ PyPI, kiểm SHA-256 và kiểm phiên bản trùng bản ghim trong `constraints.txt`.

Lỗi thì in lý do ra stderr và thoát mã 1.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packaging" / "pyinstaller"))
import third_party  # noqa: E402  (chỉ dùng thư viện chuẩn)

INIT = REPO / "src" / "teleport" / "__init__.py"
CHANGELOG = REPO / "docs" / "CHANGELOG.md"
CONSTRAINTS = REPO / "packaging" / "pyinstaller" / "constraints.txt"

_PEP440 = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:(a|b)0)?")
_PRE_TAG = {"a": "-alpha", "b": "-beta"}
# Giới hạn độ dài nội dung một GitHub Release (ký tự).
_BODY_LIMIT = 125_000

# Các dòng cố định cuối nội dung Release (Markdown, mỗi phần tử một dòng).
FIXED_NOTES = "\n".join(
    (
        "---",
        "",
        "**Trước khi tải và chạy**",
        "",
        "- {kind} Chỉ có bản Windows 10/11 64-bit: bộ cài `{setup}`, bản zip giao diện và bản zip dòng lệnh.",
        "- Bản này **chưa ký mã**: Windows SmartScreen có thể hiện “Windows protected your PC”. Bấm"
        " “More info” → “Run anyway”.",
        "- Dùng bản zip giao diện (`teleport-gui-…`) thì đọc `DOC-TRUOC.txt` trong thư mục giải nén"
        " trước khi chạy (chỗ giải nén, tường lửa, hồ sơ mạng Private).",
        "- Kiểm file tải về bằng `SHA256SUMS.txt`: trong PowerShell chạy"
        " `Get-FileHash .\\<tên file> -Algorithm SHA256` rồi so với dòng cùng tên.",
        "- Giấy phép: Teleport theo GPL-3.0-or-later; giấy phép các thành phần đi kèm ở"
        " `THIRD-PARTY-NOTICES.txt`, nơi lấy mã nguồn ở `SOURCE.txt` (cả hai nằm cạnh file exe, trong"
        " bản zip lẫn thư mục cài). Mã nguồn thư viện LGPL đóng kèm: {sources}.",
        "",
    )
)


class ReleaseError(Exception):
    """Điều kiện phát hành không đạt; workflow phải dừng."""


def app_version() -> str:
    """`__version__` trong src/teleport/__init__.py, đọc bằng ast (không chạy mã của app)."""
    tree = ast.parse(INIT.read_text(encoding="utf-8"), filename=str(INIT))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise ReleaseError(f"không thấy __version__ dạng chuỗi trong {INIT}")


def tag_for_version(version: str) -> str:
    """Tag SemVer ứng với `version` (PEP 440) theo luật hai dạng số; ngoài luật thì `ReleaseError`."""
    match = _PEP440.fullmatch(version)
    if match is None:
        raise ReleaseError(
            f"__version__ {version!r} không thuộc dạng phát hành được: X.Y.Z, X.Y.Za0 hay X.Y.Zb0"
            " (docs/CONTRIBUTING.md, Phát hành)"
        )
    major, minor, patch, pre = match.groups()
    return f"v{major}.{minor}.{patch}{_PRE_TAG.get(pre, '')}"


def is_prerelease(version: str) -> bool:
    """Bản alpha/beta là GitHub pre-release; bản thường (từ v1.0.0) là Release thường."""
    match = _PEP440.fullmatch(version)
    if match is None:
        tag_for_version(version)  # nêu lý do
        raise AssertionError("không tới được")
    return match.group(4) is not None


def check_tag(tag: str, version: str) -> None:
    expected = tag_for_version(version)
    if tag != expected:
        raise ReleaseError(f"tag {tag!r} không khớp __version__ {version!r} (cần tag {expected!r})")


def changelog_section(tag: str, text: str) -> str | None:
    """Thân mục `## [<tag bỏ v>] - YYYY-MM-DD` của CHANGELOG (tới tiêu đề `## ` kế tiếp), hoặc None."""
    title = re.compile(rf"^## \[{re.escape(tag.removeprefix('v'))}\] - \d{{4}}-\d{{2}}-\d{{2}}\s*$")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if title.match(line):
            body: list[str] = []
            for nxt in lines[i + 1 :]:
                if nxt.startswith("## "):
                    break
                body.append(nxt)
            section = "\n".join(body).strip()
            return section or None
    return None


def release_notes(tag: str, version: str, *, allow_missing: bool = False) -> str:
    section = changelog_section(tag, CHANGELOG.read_text(encoding="utf-8"))
    if section is None:
        if not allow_missing:
            raise ReleaseError(f"docs/CHANGELOG.md không có mục “## [{tag.removeprefix('v')}] - YYYY-MM-DD”")
        section = f"(Chạy khô: docs/CHANGELOG.md chưa có mục [{tag.removeprefix('v')}].)"
    kind = "Bản thử nghiệm (pre-release)." if is_prerelease(version) else "Bản phát hành."
    sources = ", ".join(
        f"`{third_party.sdist_filename(name, ver)}`"
        for name, (ver, _sha) in sorted(third_party.LGPL_SDISTS.items())
    )
    body = f"{section}\n\n" + FIXED_NOTES.format(
        kind=kind, setup=f"teleport-setup-{version}-x64.exe", sources=sources
    )
    if len(body) > _BODY_LIMIT:
        raise ReleaseError(f"nội dung Release dài {len(body)} ký tự, vượt giới hạn {_BODY_LIMIT} của GitHub")
    return body


def pinned_versions(text: str) -> dict[str, str]:
    """Bản ghim `tên==phiên bản` trong constraints.txt (tên đã chuẩn hóa)."""
    pins: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;]+)", line)
        if match:
            pins[re.sub(r"[-_.]+", "-", match.group(1)).lower()] = match.group(2)
    return pins


def fetch_sources(out: Path) -> list[Path]:
    """Tải sdist ở LGPL_SDISTS vào `out`, kiểm SHA-256 và bản ghim trong constraints.txt."""
    pins = pinned_versions(CONSTRAINTS.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, (version, sha256) in sorted(third_party.LGPL_SDISTS.items()):
        if pins.get(name) != version:
            raise ReleaseError(f"{name}: LGPL_SDISTS ghim {version}, constraints.txt ghim {pins.get(name)!r}")
        url = third_party.sdist_url(name, version)
        with urllib.request.urlopen(url, timeout=60) as resp:  # URL cố định của PyPI
            data = resp.read()
        got = hashlib.sha256(data).hexdigest()
        if got != sha256:
            raise ReleaseError(f"{name} {version}: SHA-256 của sdist là {got}, cần {sha256} ({url})")
        path = out / third_party.sdist_filename(name, version)
        path.write_bytes(data)
        print(f"{path.name}: {len(data)} B, SHA-256 {got}")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # console Windows có thể không phải UTF-8
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="in version=, tag=, prerelease= ứng với __version__")
    p_check = sub.add_parser("check-tag", help="dừng nếu tag không khớp __version__")
    p_check.add_argument("tag")
    p_notes = sub.add_parser("notes", help="ghi nội dung Release từ CHANGELOG")
    p_notes.add_argument("tag")
    p_notes.add_argument("--out", type=Path, required=True)
    p_notes.add_argument("--allow-missing", action="store_true", help="chỉ cho chạy khô")
    p_fetch = sub.add_parser("fetch-sources", help="tải sdist của thư viện LGPL và kiểm hash")
    p_fetch.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        version = app_version()
        if args.cmd == "info":
            print(f"version={version}")
            print(f"tag={tag_for_version(version)}")
            print(f"prerelease={'true' if is_prerelease(version) else 'false'}")
        elif args.cmd == "check-tag":
            check_tag(args.tag, version)
            print(f"tag {args.tag} khớp __version__ {version}")
        elif args.cmd == "notes":
            check_tag(args.tag, version)
            notes = release_notes(args.tag, version, allow_missing=args.allow_missing)
            args.out.write_text(notes, encoding="utf-8")
            print(f"{args.out}: {len(notes)} ký tự")
        elif args.cmd == "fetch-sources":
            fetch_sources(args.out)
    except (ReleaseError, third_party.LicenseAuditError, OSError) as exc:
        print(f"lỗi: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
