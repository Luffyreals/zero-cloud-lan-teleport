"""Test đơn vị cho cổng kiểm giấy phép của bản build PyInstaller (`packaging/pyinstaller/third_party.py`).

Cổng này phải đóng khi không chắc (ke_hoach mục 1, Giấy phép; docstring của module): file không rõ
thuộc gói nào, gói ngoài `APPROVED`, giấy phép khác chuỗi đã duyệt, thành phần lồng bên trong có giấy
phép ngoài tập cho phép đều làm build dừng với `LicenseAuditError`.

Module không phải gói nên nạp bằng `importlib.util.spec_from_file_location`. Test không cần PyInstaller
và không build gì: cây thư mục giả dựng trong `tmp_path` và được truyền vào tham số `base_prefix`
(`_python_dirs`, `check`) thay cho `sys.base_prefix`, nên kết quả không phụ thuộc chỗ cài trình thông
dịch thật. Bản phân phối giả (dist-info có METADATA, RECORD, SBOM) đặt trong `tmp_path` rồi thêm vào
`sys.path` để `importlib.metadata` tìm thấy.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import importlib.util
import inspect
import json
import os
import re
import shutil
import struct
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
from hypothesis import given
from hypothesis import strategies as st

_MODULE_PATH = Path(__file__).resolve().parents[2] / "packaging" / "pyinstaller" / "third_party.py"


def _load_third_party() -> ModuleType:
    name = "teleport_packaging_third_party_under_test"
    spec = importlib.util.spec_from_file_location(name, _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclass cần tìm thấy module của nó trong sys.modules
    spec.loader.exec_module(module)
    return module


tp = _load_third_party()
LicenseAuditError = tp.LicenseAuditError


def _norm(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(path))


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def _accepted(expression: str) -> bool:
    """spdx_compatible, coi `LicenseAuditError` (biểu thức hỏng) là không chấp nhận."""
    try:
        return bool(tp.spdx_compatible(expression))
    except LicenseAuditError:
        return False


# ---------------------------------------------------------------- fixture


@pytest.fixture
def base(tmp_path: Path) -> Path:
    """Thư mục cài Python giả (bố cục Windows), truyền vào tham số `base_prefix` thay cho prefix thật."""
    root = tmp_path / "Python3X"
    (root / "Lib").mkdir(parents=True)
    (root / "DLLs").mkdir()
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "packaging").mkdir()
    return root


DistMaker = Callable[..., Path]


@pytest.fixture
def make_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DistMaker:
    """Tạo bản phân phối giả mà `importlib.metadata` tìm được; trả thư mục gốc chứa dist-info."""
    root = tmp_path / "fake-site"
    root.mkdir()
    monkeypatch.syspath_prepend(str(root))

    def make(
        name: str,
        license_expression: str | None = "MIT",
        *,
        version: str = "1.0",
        sbom: dict | None = None,
        files: tuple[str, ...] = (),
    ) -> Path:
        dist_info = root / f"{name.replace('-', '_')}-{version}.dist-info"
        dist_info.mkdir()
        meta = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
        if license_expression is not None:
            meta.append(f"License-Expression: {license_expression}")
        (dist_info / "METADATA").write_text("\n".join(meta) + "\n", encoding="utf-8")
        record = [f"{dist_info.name}/METADATA,,", f"{dist_info.name}/RECORD,,"]
        if sbom is not None:
            (dist_info / "sboms").mkdir()
            (dist_info / "sboms" / "bom.cdx.json").write_text(json.dumps(sbom), encoding="utf-8")
            record.append(f"{dist_info.name}/sboms/bom.cdx.json,,")
        for rel in files:
            _touch(root / rel)
            record.append(f"{rel},,")
        (dist_info / "RECORD").write_text("\n".join(record) + "\n", encoding="utf-8")
        return root

    return make


def _classify(path: Path, base: Path) -> bool:
    """`_is_python_file` với thư mục Python của bản cài giả `base`."""
    return tp._is_python_file(_norm(path), tp._python_dirs(str(base)))


# ------------------------------------------------- 1. phân loại file của Python


@pytest.mark.parametrize(
    "rel",
    [
        "Lib/json/__init__.py",
        "Lib/struct.py",
        "DLLs/x.pyd",
        "DLLs/_ssl.pyd",
        "DLLs/libssl-3.dll",
    ],
)
def test_stdlib_and_dlls_files_count_as_python(base: Path, rel: str) -> None:
    assert _classify(_touch(base / rel), base) is True


@pytest.mark.parametrize(
    "rel",
    [
        "Lib/site-packages/evil/__init__.py",
        "Lib/site-packages/evil.pyd",
        "Lib/dist-packages/evil.py",
        "Lib/Site-Packages/evil/__init__.py",
        "Lib/DIST-PACKAGES/evil.py",
        "lib/python3.12/site-packages/evil.py",
        "site-packages/evil.dll",
    ],
)
def test_site_packages_file_without_record_is_not_python(base: Path, rel: str) -> None:
    assert _classify(_touch(base / rel), base) is False


@pytest.mark.parametrize(
    "name",
    ["python3.dll", "python312.dll", "python314.dll", "vcruntime140.dll", "vcruntime140_1.dll"],
)
def test_known_runtime_dll_at_base_prefix_root_counts_as_python(base: Path, name: str) -> None:
    assert _classify(_touch(base / name), base) is True


@pytest.mark.skipif(os.path.normcase("A") == "A", reason="hệ tệp phân biệt hoa thường: normcase giữ nguyên")
@pytest.mark.parametrize("name", ["PYTHON314.DLL", "Python3.dll", "VCRUNTIME140.DLL"])
def test_known_runtime_dll_at_root_matches_after_normcase(base: Path, name: str) -> None:
    assert _classify(base / name, base) is True


@pytest.mark.parametrize(
    "name",
    [
        "evil.dll",
        "evil.pyd",
        "evil.py",
        "xpython312.dll",
        "evil-vcruntime140.dll",
        "python312.dll.evil",
        "python314.exe",
    ],
)
def test_unknown_file_at_base_prefix_root_is_not_python(base: Path, name: str) -> None:
    assert _classify(_touch(base / name), base) is False


@pytest.mark.parametrize(
    "rel",
    ["Lib2/evil.py", "LibEvil/evil.py", "DLLs-evil/evil.pyd", "Scripts/evil.exe", "Tools/evil.py"],
)
def test_sibling_dir_of_lib_or_dlls_is_not_python(base: Path, rel: str) -> None:
    assert _classify(_touch(base / rel), base) is False


def test_file_outside_base_prefix_is_not_python(base: Path, tmp_path: Path) -> None:
    assert _classify(_touch(tmp_path / "elsewhere" / "python314.dll"), base) is False


def test_classification_follows_injected_base_prefix_not_real_one(base: Path) -> None:
    real_json = Path(inspect.getfile(json))  # json/__init__.py của trình thông dịch thật
    assert _classify(_touch(base / "Lib" / "json" / "__init__.py"), base) is True
    assert _classify(real_json, base) is False


# ----------------------------------------------- 2. check() dừng khi gặp file lạ


def _expect_unknown(
    repo: Path,
    base: Path,
    toc: list[tuple[str, str, str]],
    bad_dest: str,
    good_srcs: tuple[str, ...] = (),
) -> None:
    with pytest.raises(LicenseAuditError) as excinfo:
        tp.check(toc, repo_dir=repo, app_version="0.0.0-test", base_prefix=str(base))
    message = str(excinfo.value)
    assert bad_dest in message
    for good in good_srcs:
        assert good not in message


@pytest.mark.slow
def test_check_rejects_unknown_dll_at_base_prefix_root(base: Path, repo: Path) -> None:
    good = _touch(base / "Lib" / "json" / "__init__.py")
    evil = _touch(base / "evil_root.dll")
    toc = [("json/__init__.py", str(good), "DATA"), ("evil_root.dll", str(evil), "BINARY")]
    _expect_unknown(repo, base, toc, "evil_root.dll", (str(good),))


def test_check_rejects_parent_dir_path_resolving_to_base_root(base: Path, repo: Path) -> None:
    _touch(base / "evil_dotdot.dll")
    src = os.path.join(str(base), "Lib", "..", "evil_dotdot.dll")
    _expect_unknown(repo, base, [("evil_dotdot.dll", src, "BINARY")], "evil_dotdot.dll")


@pytest.mark.slow
@pytest.mark.parametrize(
    "rel", ["Lib/site-packages/evilpkg/core.pyd", "Lib/Site-Packages/evilpkg/__init__.py"]
)
def test_check_rejects_site_packages_file_without_record(base: Path, repo: Path, rel: str) -> None:
    good = _touch(base / "DLLs" / "_socket.pyd")
    evil = _touch(base / rel)
    toc = [("_socket.pyd", str(good), "EXTENSION"), ("evilpkg/thing", str(evil), "BINARY")]
    _expect_unknown(repo, base, toc, "evilpkg/thing", (str(good),))


def test_check_rejects_file_outside_every_known_root(base: Path, repo: Path, tmp_path: Path) -> None:
    evil = _touch(tmp_path / "downloads" / "evil_outside.dll")
    _expect_unknown(repo, base, [("evil_outside.dll", str(evil), "BINARY")], "evil_outside.dll")


@pytest.mark.slow
def test_check_rejects_unmappable_localpyc(
    base: Path, repo: Path, tmp_path: Path, make_dist: DistMaker
) -> None:
    make_dist("pyinstaller", "GPL-2.0-or-later", version="6.0")  # chỉ cần metadata, không cần PyInstaller
    pyc = _touch(tmp_path / "work" / "localpycs" / "khong_ton_tai_xyz.pyc")
    _expect_unknown(repo, base, [("khong_ton_tai_xyz", str(pyc), "PYMODULE")], "khong_ton_tai_xyz")


# ------------------------------- 2b. drop_ucrt: Universal CRT là của Windows, không đóng vào


_UCRT_SRC = r"C:\hostedtoolcache\windows\Java_Temurin-Hotspot_jdk\17.0.20-101\x64\bin"


@pytest.mark.parametrize(
    "dest",
    [
        "api-ms-win-crt-runtime-l1-1-0.dll",
        "API-MS-WIN-core-file-l1-1-0.dll",
        "api-ms-win-core-kernel32-legacy-l1-1-1.dll",
        "ucrtbase.dll",
        "UCRTBASE.DLL",
        "sub/dir/api-ms-win-crt-stdio-l1-1-0.dll",
        "sub\\ucrtbase.dll",
    ],
)
def test_drop_ucrt_removes_universal_crt(dest: str) -> None:
    entry = (dest, f"{_UCRT_SRC}\\{dest}", "BINARY")
    kept, dropped = tp.drop_ucrt([entry])
    assert kept == []
    assert dropped == [dest]


@pytest.mark.parametrize(
    "dest",
    [
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "python312.dll",
        "python3.dll",
        "_ssl.pyd",
        "libcrypto-3.dll",
        "libssl-3.dll",
        "ucrtbase.dll.txt",
        "ucrtbase.pyd",
        "xucrtbase.dll",
        "ucrtbased.dll",
        "api-ms-win-crt-runtime-l1-1-0.pyd",
        "api-ms-win-security-base-l1-1-0.dll",
        "api-ms-win-eventing-provider-l1-1-0.dll",
        "my-api-ms-win-crt-runtime-l1-1-0.dll",
        "ucrtbase.dll/evil.dll",
    ],
)
def test_drop_ucrt_keeps_other_files(dest: str) -> None:
    entry = (dest, f"C:\\Python312\\{dest}", "BINARY")
    kept, dropped = tp.drop_ucrt([entry])
    assert kept == [entry]
    assert dropped == []


def test_drop_ucrt_keeps_order_of_remaining_entries() -> None:
    toc = [
        ("python312.dll", r"C:\Python312\python312.dll", "BINARY"),
        ("ucrtbase.dll", rf"{_UCRT_SRC}\ucrtbase.dll", "BINARY"),
        ("_ssl.pyd", r"C:\Python312\DLLs\_ssl.pyd", "EXTENSION"),
        ("api-ms-win-crt-heap-l1-1-0.dll", rf"{_UCRT_SRC}\api-ms-win-crt-heap-l1-1-0.dll", "BINARY"),
        ("vcruntime140.dll", r"C:\Python312\vcruntime140.dll", "BINARY"),
    ]
    kept, dropped = tp.drop_ucrt(toc)
    assert kept == [toc[0], toc[2], toc[4]]
    assert dropped == ["ucrtbase.dll", "api-ms-win-crt-heap-l1-1-0.dll"]


@pytest.mark.parametrize("name", ["ucrtbase.dll", "api-ms-win-crt-runtime-l1-1-0.dll"])
def test_check_still_rejects_ucrt_that_was_not_dropped(
    base: Path, repo: Path, tmp_path: Path, name: str
) -> None:
    """Bộ lọc nằm ở spec, không ở cổng kiểm: UCRT lọt vào `check` vẫn là file lạ, build dừng."""
    good = _touch(base / "DLLs" / "_socket.pyd")
    ucrt = _touch(tmp_path / "jdk" / "bin" / name)
    toc = [("_socket.pyd", str(good), "EXTENSION"), (name, str(ucrt), "BINARY")]
    _expect_unknown(repo, base, toc, name, (str(good),))


@pytest.mark.parametrize("name", ["ucrtbase.dll", "api-ms-win-crt-runtime-l1-1-0.dll"])
def test_ucrt_at_base_prefix_root_is_not_python(base: Path, name: str) -> None:
    assert _classify(_touch(base / name), base) is False


# ------------------------------------------ 2. audit() dừng khi giấy phép chưa duyệt


FAKE = "teleport-test-fakepkg"


def _component(license_text: str, name: str = FAKE, version: str = "1.0") -> object:
    return tp.Component(tp._normalize(name), name, version, license_text)


def test_audit_accepts_approved_package_with_exact_license(
    make_dist: DistMaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_dist(FAKE, "MIT")
    monkeypatch.setitem(tp.APPROVED, FAKE, "MIT")
    assert tp.audit({FAKE: _component("MIT")}, {}) == {}


def test_audit_rejects_package_not_in_approved(make_dist: DistMaker) -> None:
    make_dist(FAKE, "MIT")
    assert FAKE not in tp.APPROVED
    with pytest.raises(LicenseAuditError, match=FAKE):
        tp.audit({FAKE: _component("MIT")}, {})


@pytest.mark.parametrize("declared", ["GPL-2.0-only", "MIT AND SSPL-1.0", "MIT OR GPL-2.0-only", ""])
def test_audit_rejects_license_different_from_approved_string(
    make_dist: DistMaker, monkeypatch: pytest.MonkeyPatch, declared: str
) -> None:
    make_dist(FAKE, "MIT")
    monkeypatch.setitem(tp.APPROVED, FAKE, "MIT")
    with pytest.raises(LicenseAuditError, match=FAKE):
        tp.audit({FAKE: _component(declared)}, {})


def test_audit_keeps_direct_lgpl_zeroconf_approved() -> None:
    # LGPL bị bỏ khỏi tập cho thành phần lồng bên trong, nhưng zeroconf đóng trực tiếp vẫn được duyệt.
    import importlib.metadata as md

    comp = tp.Component("zeroconf", "zeroconf", md.version("zeroconf"), tp.APPROVED["zeroconf"])
    assert tp.APPROVED["zeroconf"] == "LGPL-2.1-or-later"
    tp.audit({"zeroconf": comp}, {})


def _sbom(*components: dict) -> dict:
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": list(components)}


def _sbom_component(name: str, version: str, *licenses: dict) -> dict:
    return {"name": name, "version": version, "licenses": list(licenses)}


def _approved_fake_with_sbom(
    make_dist: DistMaker, monkeypatch: pytest.MonkeyPatch, sbom: dict
) -> dict[str, object]:
    make_dist(FAKE, "MIT", sbom=sbom)
    monkeypatch.setitem(tp.APPROVED, FAKE, "MIT")
    return {FAKE: _component("MIT")}


def test_audit_accepts_sbom_component_with_compatible_license(
    make_dist: DistMaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    sbom = _sbom(_sbom_component("crate-a", "1.2.3", {"license": {"id": "MIT"}}))
    sboms = tp.audit(_approved_fake_with_sbom(make_dist, monkeypatch, sbom), {})
    assert [entry[:3] for entry in sboms[FAKE]] == [("crate-a", "1.2.3", "MIT")]


@pytest.mark.parametrize(
    "license_item",
    [
        {"license": {"id": "LGPL-2.1-or-later"}},
        {"expression": "LGPL-2.1-or-later"},
        {"license": {"id": "GPL-2.0-only"}},
        {"expression": "MIT AND GPL-2.0-only"},
        {"license": {"name": "Giấy phép riêng"}},
    ],
)
def test_audit_rejects_sbom_component_with_disallowed_license(
    make_dist: DistMaker, monkeypatch: pytest.MonkeyPatch, license_item: dict
) -> None:
    sbom = _sbom(_sbom_component("crate-bad", "0.1.0", license_item))
    with pytest.raises(LicenseAuditError, match="crate-bad"):
        tp.audit(_approved_fake_with_sbom(make_dist, monkeypatch, sbom), {})


def test_audit_rejects_sbom_component_without_license(
    make_dist: DistMaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    sbom = _sbom(_sbom_component("mystery-lib", "2.0.0"))
    with pytest.raises(LicenseAuditError, match="mystery-lib"):
        tp.audit(_approved_fake_with_sbom(make_dist, monkeypatch, sbom), {})


def test_audit_accepts_openssl_3_without_license_in_sbom(
    make_dist: DistMaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    sbom = _sbom(_sbom_component("OpenSSL", "3.5.0"))
    sboms = tp.audit(_approved_fake_with_sbom(make_dist, monkeypatch, sbom), {})
    assert sboms[FAKE][0][2] == "Apache-2.0"


def test_audit_rejects_openssl_1_without_license_in_sbom(
    make_dist: DistMaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    sbom = _sbom(_sbom_component("OpenSSL", "1.1.1w"))
    with pytest.raises(LicenseAuditError, match="OpenSSL"):
        tp.audit(_approved_fake_with_sbom(make_dist, monkeypatch, sbom), {})


def test_audit_accepts_every_python_embedded_component() -> None:
    python_files = {entry[0]: [f"{entry[0]}x.dll"] for entry in tp.PYTHON_EMBEDDED}
    assert tp.audit({}, python_files) == {}


def test_audit_rejects_python_embedded_component_with_disallowed_license(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evil = ("_evilmod", "Evil lib", "GPL-2.0-only", "không có", ())
    monkeypatch.setattr(tp, "PYTHON_EMBEDDED", (*tp.PYTHON_EMBEDDED, evil))
    assert tp.audit({}, {}) == {}  # chưa đóng vào thì không xét
    with pytest.raises(LicenseAuditError, match="Evil lib"):
        tp.audit({}, {"_evilmod": ["_evilmod.pyd"]})


# --------------------------------------------------------- 3. spdx_compatible


@pytest.mark.parametrize(
    "expression",
    [
        "MIT",
        "Apache-2.0 OR BSD-3-Clause",
        "(MIT OR Apache-2.0) AND Unicode-3.0",
        "Apache-2.0 WITH LLVM-exception",
        "Apache-2.0 OR GPL-2.0-only",
        "GPL-2.0-only OR Apache-2.0",
        "((MIT))",
        "Apache-2.0 OR MIT AND GPL-2.0-only",
        "GPL-2.0-only AND MIT OR Apache-2.0",
        "Apache-2.0 WITH LLVM-exception OR GPL-2.0-only",
    ],
)
def test_spdx_accepts_compatible_expression(expression: str) -> None:
    assert tp.spdx_compatible(expression) is True


@pytest.mark.parametrize(
    "expression",
    [
        "GPL-2.0-only",
        "LGPL-2.1-or-later",
        "LGPL-2.1-only",
        "LGPL-3.0-or-later",
        "GPL-2.0-only OR LGPL-2.1-or-later",
        "MIT AND LGPL-2.1-or-later",
        "Teleport-Unknown-1.0",
        "MIT AND GPL-2.0-only",
        "(MIT OR Apache-2.0) AND GPL-2.0-only",
        "MIT WITH LLVM-exception",
        "mit",
    ],
)
def test_spdx_rejects_incompatible_expression(expression: str) -> None:
    assert _accepted(expression) is False


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "(MIT OR Apache-2.0",
        "MIT OR Apache-2.0)",
        "()",
        "MIT or Apache-2.0",
        "MIT and Apache-2.0",
        "Apache-2.0 with LLVM-exception",
        "MIT OR",
        "OR MIT",
        "AND",
        "MIT Apache-2.0",
        "MIT WITH",
    ],
)
def test_spdx_rejects_malformed_expression(expression: str) -> None:
    # Biểu thức hỏng: chấp nhận cả hai cách đóng cổng (ném LicenseAuditError hoặc trả False).
    assert _accepted(expression) is False


_GOOD_IDS = ("MIT", "Apache-2.0", "BSD-3-Clause", "Apache-2.0 WITH LLVM-exception")
_BAD_IDS = ("GPL-2.0-only", "SSPL-1.0", "LicenseRef-chua-duyet", "LGPL-2.1-or-later")

_Tree = str | tuple[str, list, bool]

_trees = st.recursive(
    st.sampled_from(_GOOD_IDS + _BAD_IDS),
    lambda children: st.tuples(
        st.sampled_from(("AND", "OR")), st.lists(children, min_size=2, max_size=3), st.booleans()
    ),
    max_leaves=12,
)


def _render(tree: _Tree, parent_op: str | None = None) -> str:
    if isinstance(tree, str):
        return tree
    op, children, extra_parens = tree
    text = f" {op} ".join(_render(child, op) for child in children)
    # AND gắn chặt hơn OR: OR nằm trong AND bắt buộc có ngoặc; còn lại thêm ngoặc tùy ý.
    if extra_parens or (parent_op == "AND" and op == "OR"):
        return f"({text})"
    return text


def _expected(tree: _Tree) -> bool:
    if isinstance(tree, str):
        return tree in _GOOD_IDS
    op, children, _ = tree
    values = [_expected(child) for child in children]
    return all(values) if op == "AND" else any(values)


@given(_trees)
def test_spdx_matches_reference_evaluation_with_and_binding_tighter(tree: _Tree) -> None:
    assert tp.spdx_compatible(_render(tree)) is _expected(tree)


# ------------------------------------------------------------ 4. _localpyc_source


def test_localpyc_struct_maps_to_stdlib_source_and_counts_as_python(
    tmp_path: Path, make_dist: DistMaker
) -> None:
    # Dùng thư viện chuẩn của trình thông dịch đang chạy: struct.py thật là thứ PYZ dịch sẵn.
    make_dist("pyinstaller", "GPL-2.0-or-later", version="6.0")
    pyc = _touch(tmp_path / "work" / "localpycs" / "struct.pyc")
    source = tp._localpyc_source("struct", _norm(pyc))
    assert source is not None
    expected = inspect.getsourcefile(struct)
    assert expected is not None
    assert Path(source).samefile(expected)
    assert tp._is_python_file(_norm(source), tp._python_dirs()) is True


def test_localpyc_loader_module_maps_to_pyinstaller_loader(tmp_path: Path, make_dist: DistMaker) -> None:
    root = make_dist(
        "pyinstaller",
        "GPL-2.0-or-later",
        version="6.0",
        files=("PyInstaller/loader/pyimod01_archive.py",),
    )
    pyc = _touch(tmp_path / "work" / "localpycs" / "pyimod01_archive.pyc")
    source = tp._localpyc_source("pyimod01_archive", _norm(pyc))
    assert source is not None
    assert Path(source).samefile(root / "PyInstaller" / "loader" / "pyimod01_archive.py")


@pytest.mark.parametrize(
    ("name", "rel"),
    [
        ("khong_ton_tai_xyz", "work/localpycs/khong_ton_tai_xyz.pyc"),  # không có nguồn
        ("struct", "work/other/struct.pyc"),  # không nằm trong localpycs/
        ("struct", "work/localpycs/struct.py"),  # không phải .pyc
    ],
)
def test_localpyc_source_returns_none_when_unmappable(
    tmp_path: Path, make_dist: DistMaker, name: str, rel: str
) -> None:
    make_dist("pyinstaller", "GPL-2.0-or-later", version="6.0")
    assert tp._localpyc_source(name, _norm(_touch(tmp_path / rel))) is None


# ---------------------------------------------------------- 5. remove_stale_dist


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """`dist/` có bản build cũ `teleport/` và vài thứ bên cạnh không được đụng tới."""
    root = tmp_path / "dist"
    _touch(root / tp.DIST_NAME / "teleport.exe")
    _touch(root / tp.DIST_NAME / "_internal" / "python314.dll")
    _touch(root / "ghi-chu.txt")
    _touch(root / "teleport-old" / "teleport.exe")
    return root


def test_remove_stale_dist_deletes_only_teleport_dir(dist: Path) -> None:
    assert tp.DIST_NAME == "teleport"
    assert tp.remove_stale_dist(dist, "teleport") is True
    assert not (dist / "teleport").exists()
    assert (dist / "ghi-chu.txt").is_file()
    assert (dist / "teleport-old" / "teleport.exe").is_file()


def test_remove_stale_dist_returns_false_when_nothing_to_delete(tmp_path: Path) -> None:
    (tmp_path / "dist").mkdir()
    assert tp.remove_stale_dist(tmp_path / "dist", "teleport") is False


@pytest.mark.parametrize(
    "name", ["../x", "other", "", ".", "..", "./teleport", "teleport/", "teleport/../teleport", "TELEPORT"]
)
def test_remove_stale_dist_refuses_other_names(dist: Path, name: str) -> None:
    with pytest.raises(ValueError):
        tp.remove_stale_dist(dist, name)
    assert (dist / "teleport" / "teleport.exe").is_file()
    assert (dist / "ghi-chu.txt").is_file()


def test_remove_stale_dist_refuses_dotdot_name_pointing_outside(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    victim = _touch(tmp_path / "x" / "quan-trong.txt")
    with pytest.raises(ValueError):
        tp.remove_stale_dist(dist, "../x")
    assert victim.is_file()


def test_remove_stale_dist_refuses_file_target(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    target = _touch(dist / "teleport")
    with pytest.raises(ValueError):
        tp.remove_stale_dist(dist, "teleport")
    assert target.is_file()


def test_remove_stale_dist_refuses_symlink_target(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    victim = _touch(tmp_path / "victim" / "quan-trong.txt")
    try:
        os.symlink(victim.parent, dist / "teleport", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:  # Windows không có Developer Mode/quyền tạo symlink
        pytest.skip(f"không tạo được symlink: {exc}")
    with pytest.raises(ValueError):
        tp.remove_stale_dist(dist, "teleport")
    assert victim.is_file()
    assert os.path.lexists(dist / "teleport")


@pytest.mark.skipif(sys.platform != "win32", reason="junction chỉ có trên Windows")
def test_remove_stale_dist_refuses_junction_target(tmp_path: Path) -> None:
    import _winapi

    dist = tmp_path / "dist"
    dist.mkdir()
    victim = _touch(tmp_path / "victim" / "quan-trong.txt")
    try:
        _winapi.CreateJunction(str(victim.parent), str(dist / "teleport"))
    except OSError as exc:
        pytest.skip(f"không tạo được junction: {exc}")
    try:
        with pytest.raises(ValueError):
            tp.remove_stale_dist(dist, "teleport")
        assert victim.is_file()
    finally:
        if os.path.lexists(dist / "teleport"):
            os.rmdir(dist / "teleport")  # gỡ junction, không đụng thư mục đích


def test_remove_stale_dist_works_with_relative_distpath(dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(dist.parent)
    assert tp.remove_stale_dist(Path("dist"), "teleport") is True
    assert not (dist / "teleport").exists()
    assert (dist / "ghi-chu.txt").is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="junction chỉ có trên Windows")
def test_remove_stale_dist_refuses_junction_to_sibling_inside_dist(dist: Path) -> None:
    # Junction trỏ tới thư mục ngay trong dist/: kiểm "nằm thẳng trong distpath" không bắt được,
    # chỉ còn kiểm link/junction chặn.
    import _winapi

    shutil.rmtree(dist / "teleport")
    sibling = dist / "teleport-old"
    try:
        _winapi.CreateJunction(str(sibling), str(dist / "teleport"))
    except OSError as exc:
        pytest.skip(f"không tạo được junction: {exc}")
    try:
        with pytest.raises(ValueError):
            tp.remove_stale_dist(dist, "teleport")
        assert (sibling / "teleport.exe").is_file()
    finally:
        if os.path.lexists(dist / "teleport"):
            os.rmdir(dist / "teleport")


def test_remove_stale_dist_deletes_gui_dir_and_keeps_cli(dist: Path) -> None:
    _touch(dist / tp.GUI_DIST_NAME / "Teleport.exe")
    assert tp.GUI_DIST_NAME.lower() != tp.DIST_NAME.lower()  # Windows không phân biệt hoa thường
    assert tp.remove_stale_dist(dist, tp.GUI_DIST_NAME) is True
    assert not (dist / tp.GUI_DIST_NAME).exists()
    assert (dist / tp.DIST_NAME / "teleport.exe").is_file()


@pytest.mark.parametrize("name", ["Teleport", "teleport-GUI", "teleport-gui/", "../teleport-gui"])
def test_remove_stale_dist_refuses_gui_name_variants(dist: Path, name: str) -> None:
    _touch(dist / tp.GUI_DIST_NAME / "Teleport.exe")
    with pytest.raises(ValueError):
        tp.remove_stale_dist(dist, name)
    assert (dist / tp.GUI_DIST_NAME / "Teleport.exe").is_file()


# ---------------------------------------------------------- 6. drop_files (phần Qt không dùng)


def test_drop_files_matches_dest_path_case_insensitive_with_either_separator() -> None:
    toc = [
        ("PySide6\\opengl32sw.dll", "src1", "BINARY"),
        ("PySide6/plugins/tls/qschannelbackend.dll", "src2", "BINARY"),
        ("PySide6\\Qt6Core.dll", "src3", "BINARY"),
        ("PySide6/plugins/platforms/qwindows.dll", "src4", "BINARY"),
    ]
    kept, dropped = tp.drop_files(toc, ["pyside6/opengl32sw.dll", "PySide6/plugins/tls/*"])
    assert [e[0] for e in kept] == ["PySide6\\Qt6Core.dll", "PySide6/plugins/platforms/qwindows.dll"]
    assert dropped == ["PySide6\\opengl32sw.dll", "PySide6/plugins/tls/qschannelbackend.dll"]


def test_drop_files_root_pattern_does_not_match_nested_file() -> None:
    toc = [("libssl-3-x64.dll", "a", "BINARY"), ("x/libssl-3-x64.dll", "b", "BINARY")]
    kept, dropped = tp.drop_files(toc, ["libssl-*-x64.dll"])
    assert dropped == ["libssl-3-x64.dll"]
    assert [e[0] for e in kept] == ["x/libssl-3-x64.dll"]


# ---------------------------------------------------------- 7. Qt/PySide6 (bản GUI)


def _qt_components(*files: str, version: str | None = None) -> dict[str, object]:
    comp = tp.Component(tp.QT_OWNER, "PySide6_Essentials", version or tp.QT_LICENSE_VERSION, "x")
    comp.files.extend(files)
    return {tp.QT_OWNER: comp}


def test_qt_embedded_files_empty_without_pyside() -> None:
    assert tp.qt_embedded_files({}) == []


def test_qt_embedded_files_lists_components_of_bundled_dlls_only() -> None:
    found = tp.qt_embedded_files(_qt_components("PySide6\\Qt6Core.dll", "PySide6\\MSVCP140.dll"))
    names = {entry[1] for entry, _files in found}
    assert "zlib 1.3.2" in names
    assert all(entry[0] == "pyside6/qt6core.dll" for entry, _files in found)


def test_qt_embedded_files_rejects_unreviewed_native_file() -> None:
    with pytest.raises(LicenseAuditError, match=r"qt6qml\.dll"):
        tp.qt_embedded_files(_qt_components("PySide6\\Qt6Core.dll", "PySide6\\Qt6Qml.dll"))


def test_qt_embedded_files_rejects_other_pyside_version() -> None:
    with pytest.raises(LicenseAuditError, match="rà lại"):
        tp.qt_embedded_files(_qt_components("PySide6\\Qt6Core.dll", version="6.99.0"))


def test_qt_embedded_files_rejects_disallowed_license(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = ("pyside6/qt6core.dll", "Thanh phan gia", "GPL-2.0-only", (), "")
    monkeypatch.setattr(tp, "QT_EMBEDDED", (*tp.QT_EMBEDDED, bad))
    with pytest.raises(LicenseAuditError, match="Thanh phan gia"):
        tp.qt_embedded_files(_qt_components("PySide6\\Qt6Core.dll"))


def test_every_qt_embedded_entry_is_reviewed_compatible_and_has_text() -> None:
    for pattern, name, lic, texts, _credit in tp.QT_EMBEDDED:
        assert pattern in tp.QT_REVIEWED_FILES, name
        assert tp._spdx_in(lic, tp.QT_SPDX_COMPATIBLE), name
        assert texts, name
        for file_name, source in texts:
            assert (tp.LICENSES_DIR / tp.QT_LICENSES_DIR / file_name).is_file(), file_name
            assert source.startswith("https://"), source
    for _note, texts in tp.PACKAGE_LICENSE_TEXTS.values():
        for file_name, _title, _source in texts:
            assert (tp.LICENSES_DIR / file_name).is_file(), file_name


@pytest.mark.parametrize("identifier", ["MPL-2.0", "FTL", "CC0-1.0", "Imlib2", "LicenseRef-ICC-License"])
def test_qt_only_identifiers_do_not_widen_general_set(identifier: str) -> None:
    assert identifier in tp.QT_SPDX_COMPATIBLE
    assert tp.spdx_compatible(identifier) is False


_REPO = _MODULE_PATH.parents[2]


def _real(key: str, *files: str) -> object:
    """Thành phần từ gói thật đã cài trong môi trường dev (PySide6-Essentials, shiboken6, ifaddr)."""
    import importlib.metadata as md

    dist = md.distribution(key)
    comp = tp.Component(tp._normalize(dist.name), dist.name, dist.version, tp.declared_license(dist))
    comp.files.extend(files)
    return comp


def _gui_components() -> dict[str, object]:
    qt = _real("PySide6-Essentials", "PySide6\\Qt6Core.dll", "PySide6\\Qt6Gui.dll", "PySide6\\MSVCP140.dll")
    shiboken = _real("shiboken6", "shiboken6\\shiboken6.abi3.dll")
    return {qt.key: qt, shiboken.key: shiboken}


def _gui_notices() -> str:
    pytest.importorskip("PySide6")
    comps = _gui_components()
    if comps[tp.QT_OWNER].version != tp.QT_LICENSE_VERSION:
        pytest.skip("môi trường dev cài PySide6 khác bản đã rà")
    qt_files = tp.qt_embedded_files(comps)
    return tp.build_notices(comps, {}, {}, app_version="9.9.9", edition=tp.GUI_EDITION, qt_files=qt_files)


def test_gui_notices_have_edition_lgpl_text_ftl_credit_and_msvc_note() -> None:
    notices = _gui_notices()
    assert notices.startswith("Teleport 9.9.9 (bản GUI cho Windows)")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in notices
    assert "Ghi công: Portions of this software are copyright © 2025 The FreeType Project" in notices
    assert tp.MSVC_RUNTIME_NOTE in notices
    assert "zlib 1.3.2 (trong pyside6/qt6core.dll): Zlib" in notices
    assert "LicenseRef-Qt-Commercial" not in notices  # dist-info chỉ có giấy phép thương mại: không dùng


def test_gui_notices_source_line_points_to_qt_tarball_not_pypi() -> None:
    notices = _gui_notices()
    source_lines = [line for line in notices.splitlines() if line.startswith("Mã nguồn: ")]
    assert source_lines
    assert all(line.startswith(f"Mã nguồn: {tp.PYSIDE_SOURCE_URL}") for line in source_lines)
    assert "pypi.org/project/PySide6" not in notices


def test_cli_notices_have_no_qt_section() -> None:
    comps = {"ifaddr": _real("ifaddr", "ifaddr/__init__.py")}
    notices = tp.build_notices(comps, {}, {}, app_version="9.9.9")
    assert notices.startswith("Teleport 9.9.9 (bản CLI cho Windows)")
    assert "Qt" not in notices
    assert tp.MSVC_RUNTIME_NOTE not in notices


@pytest.fixture
def build_tools_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    """`build_source` ghi phiên bản PyInstaller; CI chạy pytest không cài PyInstaller nên giả phiên bản."""
    real = tp.md.version
    fake = {"pyinstaller": "0.0.0-test", "pyinstaller-hooks-contrib": "0.0.0-test"}
    monkeypatch.setattr(tp.md, "version", lambda name: fake.get(name) or real(name))


@pytest.mark.usefixtures("build_tools_versions")
def test_gui_source_has_qt_replacement_and_tarballs() -> None:
    pytest.importorskip("PySide6")
    text = tp.build_source(_gui_components(), repo_dir=_REPO, app_version="9.9.9", edition=tp.GUI_EDITION)
    assert text.startswith("Teleport 9.9.9 (bản GUI cho Windows) - mã nguồn")
    assert "_internal\\PySide6\\" in text
    assert "không gộp vào Teleport.exe" in text
    assert tp.QT_SOURCE_URL in text
    assert tp.PYSIDE_SOURCE_URL in text


@pytest.mark.usefixtures("build_tools_versions")
def test_cli_source_has_no_qt_paragraph() -> None:
    comps = {"ifaddr": _real("ifaddr", "ifaddr/__init__.py")}
    text = tp.build_source(comps, repo_dir=_REPO, app_version="9.9.9")
    assert text.startswith("Teleport 9.9.9 (bản CLI cho Windows) - mã nguồn")
    assert "PySide6" not in text
    assert "Qt" not in text


def test_qt_set_still_rejects_gpl2_only_and_nested_lgpl() -> None:
    assert tp._spdx_in("GPL-2.0-only", tp.QT_SPDX_COMPATIBLE) is False
    assert tp._spdx_in("LGPL-2.1-or-later", tp.QT_SPDX_COMPATIBLE) is False
    assert tp._spdx_in("FTL OR GPL-2.0-only", tp.QT_SPDX_COMPATIBLE) is True


# ------------------------------------------- 8. Tài sản không phải mã (A2: icon, font)
# spec-a1-a2 mục A2 (Giấy phép) và “Áp dụng hoi-lai 30/10”: tài sản trong src/teleport/ui/assets/ là thành
# phần `asset:<key>` theo SOURCE_ASSETS, kiểm theo ASSET_LICENSES (MIT, OFL-1.1) chỉ cho tài sản; file lạ
# trong assets/ làm build dừng; NOTICES in nguyên văn MIT và OFL.

_REAL_ASSETS = _REPO / "src" / "teleport" / "ui" / "assets"
_ICON_KEY = "asset:fluentui-system-icons"
_FONT_KEY = "asset:bricolage-grotesque"
_TWO_ICON_FILES = ["teleport/ui/assets/icons/add_20_regular.svg", "teleport/ui/assets/icons/LICENSE"]


def _real_asset_rels() -> list[str]:
    """Mọi file thật dưới src/teleport/ui/assets/, tương đối với src/, dấu "/"."""
    src = _REPO / "src"
    return sorted(p.relative_to(src).as_posix() for p in _REAL_ASSETS.rglob("*") if p.is_file())


def _asset_toc(repo: Path, rels: list[str], *, copy_real: bool = True) -> list[tuple[str, str, str]]:
    """Dựng các file `rels` (tương đối với src/) trong repo giả, chép nội dung thật nếu có; trả TOC."""
    toc = []
    for rel in rels:
        target = repo / "src" / rel
        real = _REPO / "src" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if copy_real and real.is_file():
            shutil.copyfile(real, target)
        else:
            target.write_bytes(b"x")
        toc.append((rel, str(target), "DATA"))
    return toc


def _collect(repo: Path, base: Path, rels: list[str]) -> tuple[dict, dict]:
    """`collect_components` trên TOC chỉ có tài sản; trả riêng các thành phần `asset:*` (bỏ thành phần
    bootloader của PyInstaller mà hàm luôn thêm, xem fixture `fake_pyinstaller`)."""
    components, python_files = tp.collect_components(
        _asset_toc(repo, rels), repo_dir=repo, base_prefix=str(base)
    )
    assert set(components) - {"pyinstaller"} == {k for k in components if k.startswith("asset:")}
    return {k: c for k, c in components.items() if k.startswith("asset:")}, python_files


@pytest.fixture
def fake_pyinstaller(make_dist: DistMaker) -> None:
    """`collect_components` luôn ghi bootloader vào thành phần `pyinstaller`; CI chạy pytest không cài
    PyInstaller nên giả metadata (như `test_check_rejects_unmappable_localpyc`)."""
    make_dist("pyinstaller", "GPL-2.0-or-later", version="6.0")


def _matches(pattern: str, rel: str) -> bool:
    """Mẫu SOURCE_ASSETS theo docstring: `*` không vượt qua "/", không phân biệt hoa thường."""
    p_dir, _, p_base = pattern.lower().rpartition("/")
    r_dir, _, r_base = rel.lower().rpartition("/")
    return p_dir == r_dir and fnmatch.fnmatchcase(r_base, p_base)


def test_asset_licenses_are_exactly_mit_and_ofl() -> None:
    assert frozenset({"MIT", "OFL-1.1"}) == tp.ASSET_LICENSES


def test_ofl_is_rejected_outside_assets() -> None:
    assert "OFL-1.1" not in tp.SPDX_COMPATIBLE
    assert "OFL-1.1" not in tp.QT_SPDX_COMPATIBLE
    assert tp.spdx_compatible("OFL-1.1") is False
    assert tp.spdx_compatible("MIT AND OFL-1.1") is False


def test_audit_rejects_sbom_component_with_ofl(make_dist: DistMaker, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gói Python (không phải tài sản) mang OFL-1.1 qua SBOM vẫn bị chặn: OFL chỉ hợp lệ cho tài sản."""
    sbom = _sbom(_sbom_component("font-in-wheel", "1.0", {"license": {"id": "OFL-1.1"}}))
    with pytest.raises(LicenseAuditError, match="font-in-wheel"):
        tp.audit(_approved_fake_with_sbom(make_dist, monkeypatch, sbom), {})


def test_source_assets_have_two_entries_with_spec_licenses() -> None:
    by_key = {a.key: a for a in tp.SOURCE_ASSETS}
    assert set(by_key) == {"fluentui-system-icons", "bricolage-grotesque"}
    assert by_key["fluentui-system-icons"].license == "MIT"
    assert by_key["bricolage-grotesque"].license == "OFL-1.1"
    for asset in tp.SOURCE_ASSETS:
        assert asset.license in tp.ASSET_LICENSES, asset.key
        assert asset.source_url.startswith("https://"), asset.key


def test_source_assets_pin_a_commit() -> None:
    """Tài sản tải về lấy từ commit ghim (spec A2, Rủi ro): URL và phiên bản nêu cùng một SHA 40 ký tự."""
    for asset in tp.SOURCE_ASSETS:
        sha = re.search(r"\b[0-9a-f]{40}\b", asset.source_url)
        assert sha, asset.source_url
        assert sha.group(0) in asset.version, (asset.key, asset.version)


def test_every_real_asset_file_matches_exactly_one_source_asset() -> None:
    rels = _real_asset_rels()
    assert len([r for r in rels if r.endswith(".svg")]) == 48  # 47 của A2 + `color` của D6
    for rel in rels:
        owners = [a.key for a in tp.SOURCE_ASSETS if any(_matches(p, rel) for p in a.patterns)]
        assert len(owners) == 1, (rel, owners)


def test_every_source_asset_license_file_exists_and_is_covered() -> None:
    expected_text = {"MIT": "MIT License", "OFL-1.1": "SIL OPEN FONT LICENSE Version 1.1"}
    rels = _real_asset_rels()
    for asset in tp.SOURCE_ASSETS:
        path = _REPO / "src" / asset.license_file
        assert path.is_file(), asset.license_file
        assert any(_matches(p, asset.license_file) for p in asset.patterns), asset.key
        assert expected_text[asset.license] in path.read_text(encoding="utf-8"), asset.key
        mine = [r for r in rels if any(_matches(p, r) for p in asset.patterns)]
        data_files = [r for r in mine if r != asset.license_file]
        assert data_files, f"{asset.key}: không có file dữ liệu nào khớp mẫu"


@pytest.mark.usefixtures("fake_pyinstaller")
def test_collect_components_puts_real_assets_into_asset_components(repo: Path, base: Path) -> None:
    components, _python = _collect(repo, base, _real_asset_rels())
    assert set(components) == {_ICON_KEY, _FONT_KEY}
    icons, font = components[_ICON_KEY], components[_FONT_KEY]
    assert icons.license == "MIT"
    assert font.license == "OFL-1.1"
    assert len(icons.files) == 49  # 48 SVG (47 của A2 + `color` của D6) + LICENSE
    assert len(font.files) == 2  # .ttf + OFL.txt
    assert icons.license_path is not None
    assert font.license_path is not None
    assert icons.asset is not None
    assert font.asset is not None


@pytest.mark.usefixtures("fake_pyinstaller")
def test_collect_components_classifies_assets_before_project_code(repo: Path, base: Path) -> None:
    toc = _asset_toc(repo, _TWO_ICON_FILES)
    code = _touch(repo / "src" / "teleport" / "ui" / "icons.py")
    toc.append(("teleport/ui/icons.py", str(code), "DATA"))
    components, _python = tp.collect_components(toc, repo_dir=repo, base_prefix=str(base))
    assert set(components) == {_ICON_KEY, "zero-cloud-lan-teleport", "pyinstaller"}
    assert components[_ICON_KEY].files == _TWO_ICON_FILES
    project = components["zero-cloud-lan-teleport"].files
    assert "teleport/ui/icons.py" in project
    assert not [f for f in project if "assets" in f], project  # tài sản không tính vào giấy phép dự án


@pytest.mark.parametrize(
    "rel",
    [
        "teleport/ui/assets/icons/evil.png",
        "teleport/ui/assets/icons/sub/add_20_regular.svg",  # `*` không vượt qua "/"
        "teleport/ui/assets/fonts/Other.otf",
        "teleport/ui/assets/fonts/LICENSE",
        "teleport/ui/assets/README.txt",
        "teleport/ui/assets/images/logo.svg",
        "teleport/ui/assets/icons/add_20_regular.svg.bak",
    ],
)
@pytest.mark.usefixtures("fake_pyinstaller")
def test_stray_file_in_assets_stops_build(repo: Path, base: Path, rel: str) -> None:
    toc = _asset_toc(repo, _TWO_ICON_FILES) + _asset_toc(repo, [rel], copy_real=False)
    with pytest.raises(LicenseAuditError) as excinfo:
        tp.collect_components(toc, repo_dir=repo, base_prefix=str(base))
    message = str(excinfo.value)
    assert rel in message
    assert "teleport/ui/assets/icons/add_20_regular.svg <-" not in message


@pytest.mark.usefixtures("fake_pyinstaller")
def test_audit_accepts_assets_with_license_files(repo: Path, base: Path) -> None:
    components, python_files = _collect(repo, base, _real_asset_rels())
    assert tp.audit(components, python_files) == {}


@pytest.mark.usefixtures("fake_pyinstaller")
def test_audit_rejects_asset_without_its_license_file(repo: Path, base: Path) -> None:
    rels = [r for r in _real_asset_rels() if not r.endswith("/OFL.txt")]
    components, python_files = _collect(repo, base, rels)
    with pytest.raises(LicenseAuditError, match=r"OFL\.txt"):
        tp.audit(components, python_files)


@pytest.mark.usefixtures("fake_pyinstaller")
def test_audit_rejects_asset_with_license_outside_asset_licenses(
    repo: Path, base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpl2 = tuple(
        dataclasses.replace(a, license="GPL-2.0-only") if a.key == "fluentui-system-icons" else a
        for a in tp.SOURCE_ASSETS
    )
    monkeypatch.setattr(tp, "SOURCE_ASSETS", gpl2)
    components, python_files = _collect(repo, base, _real_asset_rels())
    with pytest.raises(LicenseAuditError, match="Fluent UI System Icons"):
        tp.audit(components, python_files)


@pytest.mark.usefixtures("fake_pyinstaller")
def test_notices_quote_mit_and_ofl_for_assets(repo: Path, base: Path) -> None:
    components, python_files = _collect(repo, base, _real_asset_rels())
    notices = tp.build_notices(components, python_files, {}, app_version="9.9.9", edition=tp.GUI_EDITION)
    assert "Fluent UI System Icons" in notices
    assert "Bricolage Grotesque" in notices
    assert "MIT License" in notices
    assert "SIL OPEN FONT LICENSE Version 1.1" in notices
    # Nguyên văn: cả văn bản LICENSE của icon và OFL.txt của font nằm trong NOTICES.
    mit = (_REAL_ASSETS / "icons" / "LICENSE").read_text(encoding="utf-8").strip()
    ofl = (_REAL_ASSETS / "fonts" / "OFL.txt").read_text(encoding="utf-8").strip()
    assert mit in notices
    assert ofl in notices
    for asset in tp.SOURCE_ASSETS:
        assert asset.source_url in notices


@pytest.mark.usefixtures("build_tools_versions", "fake_pyinstaller")
def test_gui_source_lists_icon_font_and_qtsvg_urls(repo: Path, base: Path) -> None:
    pytest.importorskip("PySide6")
    comps = _gui_components()
    comps[tp.QT_OWNER].files.append("PySide6\\Qt6Svg.dll")
    asset_comps, _python = _collect(repo, base, _real_asset_rels())
    comps.update(asset_comps)
    text = tp.build_source(comps, repo_dir=_REPO, app_version="9.9.9", edition=tp.GUI_EDITION)
    assert "qtsvg-everywhere-src-6.12.0.tar.xz" in text
    for asset in tp.SOURCE_ASSETS:
        assert asset.source_url in text


def test_qtsvg_dll_and_pyd_are_reviewed_but_svgwidgets_is_not() -> None:
    assert "pyside6/qt6svg.dll" in tp.QT_REVIEWED_FILES
    assert "pyside6/qtsvg.pyd" in tp.QT_REVIEWED_FILES
    tp.qt_embedded_files(_qt_components("PySide6\\Qt6Core.dll", "PySide6\\Qt6Svg.dll", "PySide6\\QtSvg.pyd"))
    with pytest.raises(LicenseAuditError, match=r"qt6svgwidgets\.dll"):
        tp.qt_embedded_files(_qt_components("PySide6\\Qt6Svg.dll", "PySide6\\Qt6SvgWidgets.dll"))


def test_pyproject_license_and_package_data_cover_assets() -> None:
    project = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["license"] == "GPL-3.0-or-later AND MIT AND OFL-1.1"
    assert tp.APPROVED["zero-cloud-lan-teleport"] == project["project"]["license"]
    license_files = set(project["project"]["license-files"])
    needed = {"LICENSE", "src/teleport/ui/assets/icons/LICENSE", "src/teleport/ui/assets/fonts/OFL.txt"}
    assert needed <= license_files
    globs = project["tool"]["setuptools"]["package-data"]["teleport.ui"]
    ui_dir = _REPO / "src" / "teleport" / "ui"
    covered = {p.relative_to(ui_dir).as_posix() for g in globs for p in ui_dir.glob(g) if p.is_file()}
    real = {p.relative_to(ui_dir).as_posix() for p in _REAL_ASSETS.rglob("*") if p.is_file()}
    assert real <= covered, sorted(real - covered)


# ---------------------------------------------------------------- bản phát hành (TELEPORT_RELEASE_TAG)
# Đặc tả: docs/CONTRIBUTING.md mục “Phát hành” (workflow đặt TELEPORT_RELEASE_TAG để SOURCE.txt chỉ tới
# sdist zeroconf trên trang Release của tag; LGPL_SDISTS phải bằng bản ghim trong constraints.txt) và
# docstring của third_party.py (bản build thử chỉ ghi link PyPI).


def _constraints_pins() -> dict[str, str]:
    text = (_REPO / "packaging" / "pyinstaller" / "constraints.txt").read_text(encoding="utf-8")
    pins: dict[str, str] = {}
    for line in text.splitlines():
        m = re.fullmatch(r"([A-Za-z0-9._-]+)==(\S+)", line.strip())
        if m:
            pins[m.group(1).lower()] = m.group(2)
    return pins


def test_release_tag_is_none_when_env_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEPORT_RELEASE_TAG", raising=False)
    assert tp.release_tag() is None


@pytest.mark.parametrize("value", ["", "   "])
def test_release_tag_is_none_when_env_empty(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("TELEPORT_RELEASE_TAG", value)
    assert tp.release_tag() is None


@pytest.mark.parametrize("tag", ["v0.1.0-alpha", "v0.3.0-beta", "v1.0.0", "v10.20.30"])
def test_release_tag_accepts_release_tag_forms(monkeypatch: pytest.MonkeyPatch, tag: str) -> None:
    monkeypatch.setenv("TELEPORT_RELEASE_TAG", tag)
    assert tp.release_tag() == tag


@pytest.mark.parametrize(
    "tag",
    [
        "v0.1.0-alpha; rm -rf /",
        "v0.1.0-alpha;rm",
        "v0.1.0-alpha && calc",
        "v0.1.0-alpha$(id)",
        "v0.1.0-alpha`id`",
        "v0.1.0-alpha\nrm",
        "v0.1.0-alpha/../../x",
        "v0.1.0-alpha\\..\\x",
        "v0.1.0-alpha x",
        "v0.1.0a0",
        "0.1.0-alpha",
        "V0.1.0-alpha",
        "v0.1.0-Alpha",
        "v0.1.0-rc1",
        "v0.1.0-alpha.1",
        "v0.1.0-alpha1",
        "v0.1",
        "v1.0.0.0",
        "main",
        "refs/tags/v0.1.0-alpha",
        "v١.0.0",  # chữ số Ả Rập
    ],
)
def test_release_tag_rejects_malformed_or_injected_value(monkeypatch: pytest.MonkeyPatch, tag: str) -> None:
    monkeypatch.setenv("TELEPORT_RELEASE_TAG", tag)
    with pytest.raises(LicenseAuditError):
        tp.release_tag()


@pytest.mark.parametrize("tag", ["v01.0.0", "v1.00.0", "v1.0.01"])
def test_release_tag_rejects_leading_zero_numbers(monkeypatch: pytest.MonkeyPatch, tag: str) -> None:
    """SemVer (CONTRIBUTING.md: “Đánh số theo SemVer”) cấm số có 0 đầu."""
    monkeypatch.setenv("TELEPORT_RELEASE_TAG", tag)
    with pytest.raises(LicenseAuditError):
        tp.release_tag()


def _zeroconf_component(version: str) -> object:
    return tp.Component("zeroconf", "zeroconf", version, "LGPL-2.1-or-later", ["zeroconf/__init__.py"])


def _repo_url() -> str:
    project = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return project["project"]["urls"]["Repository"].rstrip("/")


def test_lgpl_sdists_match_constraints_pins() -> None:
    pins = _constraints_pins()
    assert "zeroconf" in tp.LGPL_SDISTS
    for name, (version, sha) in tp.LGPL_SDISTS.items():
        assert pins.get(name) == version, name
        assert re.fullmatch(r"[0-9a-f]{64}", sha), name


@pytest.mark.usefixtures("build_tools_versions")
def test_release_source_points_to_zeroconf_sdist_on_release_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEPORT_RELEASE_TAG", "v0.1.0-alpha")
    version, sha = tp.LGPL_SDISTS["zeroconf"]
    text = tp.build_source({"zeroconf": _zeroconf_component(version)}, repo_dir=_REPO, app_version="0.1.0a0")
    repo = _repo_url()
    release_lines = [line for line in text.splitlines() if f"{repo}/releases/tag/v0.1.0-alpha" in line]
    assert release_lines, "thiếu dòng bản phát hành"
    assert f"{repo}/releases/download/v0.1.0-alpha/zeroconf-{version}.tar.gz" in text
    assert sha in text


@pytest.mark.usefixtures("build_tools_versions")
def test_release_source_stops_when_bundled_zeroconf_differs_from_lgpl_sdists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEPORT_RELEASE_TAG", "v0.1.0-alpha")
    version, _sha = tp.LGPL_SDISTS["zeroconf"]
    with pytest.raises(LicenseAuditError):
        tp.build_source(
            {"zeroconf": _zeroconf_component(version + ".1")}, repo_dir=_REPO, app_version="0.1.0a0"
        )


@pytest.mark.usefixtures("build_tools_versions")
def test_release_source_stops_when_zeroconf_missing_from_lgpl_sdists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEPORT_RELEASE_TAG", "v0.1.0-alpha")
    version, _sha = tp.LGPL_SDISTS["zeroconf"]
    monkeypatch.setattr(tp, "LGPL_SDISTS", {})
    with pytest.raises(LicenseAuditError):
        tp.build_source({"zeroconf": _zeroconf_component(version)}, repo_dir=_REPO, app_version="0.1.0a0")


@pytest.mark.usefixtures("build_tools_versions")
def test_release_source_stops_on_malformed_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEPORT_RELEASE_TAG", "v0.1.0-alpha; rm")
    version, _sha = tp.LGPL_SDISTS["zeroconf"]
    with pytest.raises(LicenseAuditError):
        tp.build_source({"zeroconf": _zeroconf_component(version)}, repo_dir=_REPO, app_version="0.1.0a0")


@pytest.mark.usefixtures("build_tools_versions")
def test_test_build_source_has_only_pypi_link_and_no_release_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEPORT_RELEASE_TAG", raising=False)
    version, sha = tp.LGPL_SDISTS["zeroconf"]
    for v in (version, version + ".1"):  # bản build thử không cần zeroconf trùng LGPL_SDISTS
        text = tp.build_source({"zeroconf": _zeroconf_component(v)}, repo_dir=_REPO, app_version="9.9.9")
        assert "releases/" not in text
        assert sha not in text
        assert "Bản phát hành" not in text
        zeroconf_lines = [line for line in text.splitlines() if line.startswith("Mã nguồn zeroconf: ")]
        assert len(zeroconf_lines) == 1
        assert "http" in zeroconf_lines[0]
        assert f"Thư viện LGPL: zeroconf {v} (LGPL-2.1-or-later)" in text


@pytest.mark.usefixtures("build_tools_versions")
def test_release_source_keeps_every_line_of_test_build_except_pypi_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bản phát hành chỉ thêm dòng, không bỏ thông tin nào khác của SOURCE.txt bản build thử."""
    version, _sha = tp.LGPL_SDISTS["zeroconf"]
    comps = {"zeroconf": _zeroconf_component(version)}
    monkeypatch.setenv("GITHUB_SHA", "0" * 40)
    monkeypatch.delenv("TELEPORT_RELEASE_TAG", raising=False)
    plain = tp.build_source(comps, repo_dir=_REPO, app_version="0.1.0a0").splitlines()
    monkeypatch.setenv("TELEPORT_RELEASE_TAG", "v0.1.0-alpha")
    release = tp.build_source(comps, repo_dir=_REPO, app_version="0.1.0a0").splitlines()
    kept = [line for line in plain if not line.startswith("Mã nguồn zeroconf: ")]
    missing = [line for line in kept if line not in release]
    assert missing == []


# ---------------------------------------------------------------- sbom_notice_texts


def _entry(name: str, version: str, expression: str) -> tuple[str, str, str, str]:
    return (name, version, expression, "pkg:cargo/" + name)


def _table_key() -> tuple[str, str, str]:
    return sorted(tp.SBOM_NOTICE_TEXTS)[0]


@pytest.mark.parametrize(
    "expression", ["MIT", "BSD-3-Clause", "MIT AND Apache-2.0", "(MIT OR Apache-2.0) AND Unicode-3.0"]
)
def test_sbom_notice_rejects_component_needing_own_text_not_in_table(expression: str) -> None:
    assert ("cryptography", "crate-chua-co", "1.0.0") not in tp.SBOM_NOTICE_TEXTS
    with pytest.raises(LicenseAuditError, match="crate-chua-co"):
        tp.sbom_notice_texts("cryptography", [_entry("crate-chua-co", "1.0.0", expression)])


@pytest.mark.parametrize(
    "expression", ["MIT OR Apache-2.0", "Apache-2.0", "Apache-2.0 OR MIT", "Apache-2.0 WITH LLVM-exception"]
)
def test_sbom_notice_uses_package_apache_text_for_apache_branch(expression: str) -> None:
    own, uses_owner = tp.sbom_notice_texts("cryptography", [_entry("crate-chua-co", "1.0.0", expression)])
    assert own == []
    assert uses_owner is True


def test_sbom_notice_empty_sbom_needs_nothing() -> None:
    assert tp.sbom_notice_texts("cryptography", []) == ([], False)


def test_sbom_notice_returns_texts_of_listed_component() -> None:
    key, name, version = _table_key()
    own, uses_owner = tp.sbom_notice_texts(key, [_entry(name, version, "MIT")])
    assert uses_owner is False
    assert len(own) == 1
    got_name, got_version, got_expr, texts = own[0]
    assert (got_name, got_version, got_expr) == (name, version, "MIT")
    assert texts == list(tp.SBOM_NOTICE_TEXTS[(key, name, version)])


def test_sbom_notice_lookup_ignores_case_of_component_name() -> None:
    key, name, version = _table_key()
    own, _uses = tp.sbom_notice_texts(key, [_entry(name.upper(), version, "MIT")])
    assert len(own) == 1


def test_sbom_notice_rejects_listed_component_whose_text_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key, name, version = _table_key()
    tp.sbom_notice_texts(key, [_entry(name, version, "MIT")])  # đối chứng: có file thì qua
    monkeypatch.setattr(tp, "LICENSES_DIR", tmp_path / "licenses-rong")
    with pytest.raises(LicenseAuditError, match=re.escape(name)):
        tp.sbom_notice_texts(key, [_entry(name, version, "MIT")])


def test_sbom_notice_rejects_other_version_of_listed_component() -> None:
    key, name, version = _table_key()
    with pytest.raises(LicenseAuditError):
        tp.sbom_notice_texts(key, [_entry(name, version + ".99", "MIT")])


def test_sbom_notice_rejects_listed_component_under_other_package() -> None:
    _key, name, version = _table_key()
    with pytest.raises(LicenseAuditError):
        tp.sbom_notice_texts("goi-khac", [_entry(name, version, "MIT")])


def test_sbom_notice_mixed_entries_still_stop_on_missing_one() -> None:
    entries = [_entry("a", "1.0.0", "MIT OR Apache-2.0"), _entry("crate-chua-co", "1.0.0", "MIT")]
    with pytest.raises(LicenseAuditError, match="crate-chua-co"):
        tp.sbom_notice_texts("cryptography", entries)


def test_every_sbom_notice_text_exists_and_matches_pinned_package_version() -> None:
    """Văn bản chép sẵn có mặt, không rỗng, và nằm trong thư mục đúng bản ghim ở constraints.txt."""
    pins = _constraints_pins()
    assert tp.SBOM_NOTICE_TEXTS
    for (key, name, version), texts in tp.SBOM_NOTICE_TEXTS.items():
        assert name == name.lower()
        assert texts
        for file_name, source in texts:
            path = tp.LICENSES_DIR / file_name
            assert path.is_file(), file_name
            assert path.read_text(encoding="utf-8").strip(), file_name
            assert file_name.startswith(f"{key}-{pins[key]}/"), file_name
            assert f"{name}-{version}" in file_name, file_name
            assert source.startswith("https://"), source
