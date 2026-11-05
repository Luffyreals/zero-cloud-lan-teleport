"""Kiểm giấy phép và sinh `THIRD-PARTY-NOTICES.txt`, `SOURCE.txt` cho bản build PyInstaller.

`teleport-cli.spec` và `teleport-gui.spec` gọi `check` ngay sau Analysis/PYZ (trước EXE/COLLECT) và
`write_outputs` sau COLLECT, chạy trong chính môi trường Python dùng để build (`edition` chọn tên bản
và tên exe trong các file sinh ra).
Danh sách thành phần lấy từ các file PyInstaller thật sự đóng vào (TOC của `Analysis` và module khởi
động `PYZ.dependencies`), rồi tra
ngược file đó thuộc bản phân phối nào qua `RECORD` của gói đã cài (`importlib.metadata`), nên gồm
cả dependency gián tiếp. Văn bản giấy phép lấy từ dist-info của từng gói. Python lấy `LICENSE.txt`
của trình thông dịch dùng để build, cộng văn bản chép sẵn trong `licenses/` cho phần mềm tích hợp
trong CPython và thư viện C của bản Windows mà `LICENSE.txt` không có (`CPYTHON_LICENSE_TEXTS`,
`PYTHON_EMBEDDED`, theo đúng phiên bản Python). Gói có SBOM CycloneDX trong `.dist-info/sboms/`
(PEP 770, ví dụ `cryptography` liên kết tĩnh OpenSSL và các crate Rust) thì liệt kê và kiểm cả thành
phần trong SBOM; thành phần SBOM có giấy phép đòi giữ dòng bản quyền mà văn bản Apache-2.0 của gói
không thay được (ví dụ crate chỉ theo MIT như `openssl-sys`, `pem`) phải có văn bản chép sẵn đúng phiên
bản (`SBOM_NOTICE_TEXTS`, thư mục `licenses/<gói>-<phiên bản>/`). Qt/PySide6 (bản GUI) không có SBOM
trong wheel: thành phần lồng trong DLL Qt lấy từ bảng `QT_EMBEDDED` (rà theo qt_attribution.json
đúng phiên bản Qt), văn bản chép sẵn trong `licenses/qt-<phiên bản>/`.

Tài sản không phải mã (icon SVG, font) nằm trong `src/teleport/ui/assets/` không thuộc gói Python nào
của bên thứ ba: chúng là thành phần riêng `asset:<key>` theo bảng `SOURCE_ASSETS` (nguồn, commit ghim,
giấy phép, file giấy phép đi kèm), kiểm theo `ASSET_LICENSES` chứ không theo `APPROVED`, và được xếp
loại trước khi tra RECORD hay mã của dự án. File trong `assets/` không khớp mục nào làm build dừng.

Bản phát hành (workflow `release.yml` đặt biến `TELEPORT_RELEASE_TAG`): `SOURCE.txt` chỉ tới sdist của
thư viện LGPL (`LGPL_SDISTS`) đính kèm trang GitHub Release của tag; bản build thử chỉ ghi link PyPI.

Luật (ke_hoach mục 1, Giấy phép): mọi thứ đóng vào phải tương thích GPLv3. Gói nằm ngoài
`APPROVED`, gói có giấy phép trong metadata khác chuỗi đã duyệt, file không biết thuộc gói nào,
hay thành phần SBOM có giấy phép ngoài `SPDX_COMPATIBLE` đều làm build dừng với `LicenseAuditError`:
không rõ thì báo, không đoán. Thêm hay nâng dependency mà đổi giấy phép thì phải duyệt lại rồi sửa
`APPROVED` ở đây.
"""

from __future__ import annotations

import contextlib
import fnmatch
import importlib.metadata as md
import json
import os
import platform
import re
import shutil
import site
import ssl
import subprocess
import sys
import sysconfig
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# Tên bản phân phối (đã chuẩn hóa) -> chuỗi giấy phép đúng như metadata của gói (License-Expression,
# không có thì License, không có nữa thì các classifier License). Đã đối chiếu tương thích GPLv3.
APPROVED: dict[str, str] = {
    # Wheel của dự án chứa cả icon (MIT) và font (OFL-1.1) trong teleport/ui/assets/ (PEP 639). Trong
    # bản build PyInstaller, các file đó là thành phần tài sản riêng (SOURCE_ASSETS), không thuộc gói này.
    "zero-cloud-lan-teleport": "GPL-3.0-or-later AND MIT AND OFL-1.1",
    "cryptography": "Apache-2.0 OR BSD-3-Clause",
    "cffi": "MIT-0",
    "pycparser": "BSD-3-Clause",
    "zeroconf": "LGPL-2.1-or-later",
    "ifaddr": "MIT",
    # Chỉ bootloader (nhúng trong teleport.exe / Teleport.exe), module loader và runtime hook được đóng vào:
    # bootloader theo GPL-2.0-or-later kèm Bootloader Exception, runtime hook theo Apache-2.0.
    "pyinstaller": (
        "GPLv2-or-later with a special exception which allows to use PyInstaller to build "
        "and distribute non-free programs (including commercial ones)"
    ),
    # Chỉ runtime hook được đóng vào, và runtime hook theo Apache-2.0 (file LICENSE của gói).
    "pyinstaller-hooks-contrib": (
        "License :: OSI Approved :: Apache Software License; "
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)"
    ),
    # Bản GUI: Qt và PySide6 (gói PySide6-Essentials, kèm shiboken6). Dùng theo nhánh LGPL-3.0-only:
    # DLL Qt và module PySide6 là file riêng trong _internal\PySide6\ (--onedir), người dùng thay được.
    # Văn bản giấy phép lấy từ PACKAGE_LICENSE_TEXTS (dist-info của hai gói chỉ có giấy phép thương mại).
    "pyside6-essentials": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
    "shiboken6": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
}

# Giấy phép được chấp nhận cho thành phần LỒNG BÊN TRONG một gói hay một runtime đã duyệt (thành phần
# trong SBOM của gói, thư viện C và mã tích hợp trong CPython ở PYTHON_EMBEDDED). Nguồn quyết định là
# ke_hoach mục 1 (Giấy phép): gói đóng vào trực tiếp phải nằm trong APPROVED; thành phần lồng bên trong
# được dùng thêm các giấy phép dễ dãi tương thích GPLv3 liệt kê ở đây. Ngoài tập này thì build dừng;
# muốn thêm định danh thì sửa ke_hoach mục 1 trước rồi mới sửa tập này.
# Cố ý KHÔNG có LGPL: theo ke_hoach mục 1, LGPL chỉ dùng được cho gói đóng vào dạng file riêng mà người
# dùng thay được (đi qua APPROVED, ví dụ zeroconf), không cho thành phần lồng bên trong/liên kết tĩnh,
# vì người dùng không thay được phần đó.
# Biểu thức có OR thì chỉ cần một nhánh nằm trong tập, có AND thì mọi vế phải nằm trong tập.
SPDX_COMPATIBLE: frozenset[str] = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "Apache-2.0 WITH LLVM-exception",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "bzip2-1.0.6",
        "ISC",
        "MIT",
        "MIT-0",
        "PSF-2.0",
        "Unicode-3.0",
        "Unicode-DFS-2016",
        "Zlib",
        # Không có định danh SPDX chắc chắn nên đặt tên LicenseRef riêng (văn bản ở license.rst/COPYING).
        # Mỗi tên ứng với đúng một mục trong dòng Giấy phép của ke_hoach mục 1:
        "LicenseRef-public-domain",  # mục "public domain" của §1; ở đây: liblzma (XZ Utils 5.2.5)
        # mục "giấy phép chỉ đòi giữ thông báo của dtoa.c (David M. Gay, trong lõi CPython)" của §1
        "LicenseRef-dtoa-notice",
        # mục "DLL runtime MSVC (vcruntime140*.dll) ... ngoại lệ System Library của GPLv3" của §1
        "LicenseRef-MSVC-runtime-system-library",
    }
)

# ---- Tài sản không phải mã (icon, font) trong src/teleport/ui/assets/ ------------------------------
# Giấy phép được chấp nhận cho tài sản trong SOURCE_ASSETS, và CHỈ cho chúng (không mở rộng cho gói,
# SBOM hay Qt). MIT (icon) tương thích GPLv3. OFL-1.1 (font) không phải "tương thích GPLv3": file font
# được đóng nguyên dạng, là file dữ liệu riêng kèm OFL.txt, cùng phân phối với chương trình như một tác
# phẩm gộp (ke_hoach mục 1, Giấy phép). Muốn thêm định danh thì sửa ke_hoach mục 1 trước.
ASSET_LICENSES: frozenset[str] = frozenset({"MIT", "OFL-1.1"})


@dataclass(frozen=True)
class SourceAsset:
    """Một bộ tài sản lấy nguyên dạng từ dự án bên thứ ba, ghim theo commit.

    `patterns`: mẫu đường dẫn (dấu "/", tương đối với `src/`, cũng là đường dẫn đích trong bản build)
    của các file thuộc bộ này; `*` không vượt qua "/". `license_file`: file giấy phép đi kèm (cũng
    phải được đóng vào, văn bản của nó vào THIRD-PARTY-NOTICES.txt).
    """

    key: str
    name: str
    version: str  # bản phát hành hoặc commit đã ghim ở nguồn
    license: str  # biểu thức SPDX, kiểm theo ASSET_LICENSES
    patterns: tuple[str, ...]
    license_file: str
    source_url: str  # nơi lấy đúng các file đã chép (trỏ tới commit đã ghim)


_FLUENT_SHA = "64e5aa757d1b70c24a283256ddcb8269d0f58773"
_GOOGLE_FONTS_SHA = "6ce172f74aa355ea43eb964fa4a91570a4d3064d"
# Thư mục chứa tài sản, tương đối với src/. Mọi file đóng vào từ đây phải khớp một mục SOURCE_ASSETS.
ASSETS_ROOT = "teleport/ui/assets"
SOURCE_ASSETS: tuple[SourceAsset, ...] = (
    SourceAsset(
        key="fluentui-system-icons",
        name="Fluent UI System Icons",
        # Mỗi SVG chép nguyên văn từ assets/<Tên Thư Mục>/SVG/ic_fluent_<tên>_<cỡ>_regular.svg của commit
        # này, đổi tên thành <tên>_<cỡ>_regular.svg; LICENSE là file LICENSE ở gốc repo cùng commit.
        version=f"commit {_FLUENT_SHA}",
        license="MIT",
        patterns=(f"{ASSETS_ROOT}/icons/*.svg", f"{ASSETS_ROOT}/icons/LICENSE"),
        license_file=f"{ASSETS_ROOT}/icons/LICENSE",
        source_url=f"https://github.com/microsoft/fluentui-system-icons/tree/{_FLUENT_SHA}/assets",
    ),
    SourceAsset(
        key="bricolage-grotesque",
        name="Bricolage Grotesque",
        # BricolageGrotesque.ttf là ofl/bricolagegrotesque/BricolageGrotesque[opsz,wdth,wght].ttf của
        # commit google/fonts dưới đây (đổi tên, nội dung không đổi); OFL.txt cùng thư mục, cùng commit.
        version=f"1.001 (font biến thiên), google/fonts commit {_GOOGLE_FONTS_SHA}",
        license="OFL-1.1",
        patterns=(f"{ASSETS_ROOT}/fonts/*.ttf", f"{ASSETS_ROOT}/fonts/OFL.txt"),
        license_file=f"{ASSETS_ROOT}/fonts/OFL.txt",
        source_url=(
            f"https://github.com/google/fonts/tree/{_GOOGLE_FONTS_SHA}/ofl/bricolagegrotesque"
            " (dự án gốc: https://github.com/ateliertriay/bricolage)"
        ),
    ),
)


def _match_asset(rel: str) -> tuple[SourceAsset, bool] | None:
    """Mục SOURCE_ASSETS mà đường dẫn `rel` (tương đối với src/, dấu "/") thuộc về, và `rel` có phải
    file giấy phép của mục đó không. Không khớp thì None. So không phân biệt hoa thường (Windows)."""
    rel_l = rel.lower()
    folder, _, base = rel_l.rpartition("/")
    for asset in SOURCE_ASSETS:
        for pattern in asset.patterns:
            p_folder, _, p_base = pattern.lower().rpartition("/")
            if folder == p_folder and fnmatch.fnmatchcase(base, p_base):
                return asset, rel_l == asset.license_file.lower()
    return None


# Thành phần SBOM mà metadata không ghi giấy phép: tên -> (bản chính tối thiểu, SPDX, nguồn dữ kiện).
SBOM_KNOWN_LICENSES: dict[str, tuple[int, str, str]] = {
    # OpenSSL đổi sang Apache-2.0 từ bản 3.0.0.
    "openssl": (3, "Apache-2.0", "https://openssl-library.org/source/license/"),
}

# Thành phần SBOM mà biểu thức giấy phép thỏa được chỉ bằng các định danh dưới đây thì dùng theo nhánh
# đó, văn bản là file giấy phép Apache-2.0 trong dist-info của chính gói chứa nó (`build_notices` kiểm
# văn bản đó có mặt). Đã xem 05/11 cho cryptography 50.0.2: không crate nào trong SBOM có file NOTICE.
SBOM_OWNER_TEXT_LICENSES: frozenset[str] = frozenset({"Apache-2.0", "Apache-2.0 WITH LLVM-exception"})
_APACHE_TEXT = re.compile(r"Apache License\s+Version 2\.0")

# Thành phần SBOM còn lại (giấy phép đòi kèm thông báo bản quyền mà gói không có văn bản: MIT, BSD-3-Clause,
# Unicode-3.0, ...): văn bản nguyên văn của ĐÚNG phiên bản, chép sẵn trong licenses/<gói>-<phiên bản>/.
# Khóa: (gói đã chuẩn hóa, tên thành phần trong SBOM chữ thường, phiên bản) -> các (file trong licenses/,
# nguồn đã chép). Thiếu khóa thì build dừng (`sbom_notice_texts`): nâng gói thì lấy văn bản của bản mới
# cùng nguồn rồi sửa bảng. Nguồn: file .crate chính thức trên crates.io, SHA-256 khớp hash trong SBOM.
_CRATE = "https://static.crates.io/crates/{0}/{0}-{1}.crate (file {2}; SHA-256 của .crate khớp SBOM)"
SBOM_NOTICE_TEXTS: dict[tuple[str, str, str], tuple[tuple[str, str], ...]] = {
    ("cryptography", "asn1", "0.24.1"): (
        ("cryptography-50.0.2/asn1-0.24.1-LICENSE.txt", _CRATE.format("asn1", "0.24.1", "LICENSE")),
    ),
    ("cryptography", "asn1_derive", "0.24.1"): (
        (
            "cryptography-50.0.2/asn1_derive-0.24.1-LICENSE.txt",
            _CRATE.format("asn1_derive", "0.24.1", "LICENSE"),
        ),
    ),
    ("cryptography", "openssl-sys", "0.9.117"): (
        (
            "cryptography-50.0.2/openssl-sys-0.9.117-LICENSE-MIT.txt",
            _CRATE.format("openssl-sys", "0.9.117", "LICENSE-MIT"),
        ),
    ),
    ("cryptography", "pem", "4.0.0"): (
        ("cryptography-50.0.2/pem-4.0.0-LICENSE.md", _CRATE.format("pem", "4.0.0", "LICENSE.md")),
    ),
    # (MIT OR Apache-2.0) AND Unicode-3.0: nhánh Apache-2.0 dùng văn bản của gói, vế Unicode-3.0 cần
    # văn bản riêng.
    ("cryptography", "unicode-ident", "1.0.24"): (
        (
            "cryptography-50.0.2/unicode-ident-1.0.24-LICENSE-UNICODE.txt",
            _CRATE.format("unicode-ident", "1.0.24", "LICENSE-UNICODE"),
        ),
    ),
}

# Mã nguồn thư viện LGPL đóng vào, đính kèm trang GitHub Release của tag (LGPL-2.1 §6(d): bản nhị phân
# phát từ một nơi thì cho chép mã nguồn từ cùng nơi đó). Tên bản phân phối -> (phiên bản, SHA-256 của
# sdist trên PyPI). Phiên bản phải bằng bản ghim trong constraints.txt; `packaging/release/release.py`
# tải sdist từ PyPI và kiểm hash này, `build_source` ghi link khi build cho bản phát hành.
LGPL_SDISTS: dict[str, tuple[str, str]] = {
    "zeroconf": ("0.151.5", "28c2ec9d772007eedf11b41a9c9fd3d5c684c17b00721ff8f1ee31b20ad286a1"),
}
# Biến môi trường workflow phát hành đặt khi build (tag, ví dụ v0.1.0-alpha). Không có thì là bản build thử.
RELEASE_TAG_ENV = "TELEPORT_RELEASE_TAG"
_RELEASE_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-alpha|-beta)?")


def sdist_filename(dist_name: str, version: str) -> str:
    """Tên file sdist trên PyPI (PEP 625: tên chuẩn hóa với "_")."""
    return f"{re.sub(r'[-_.]+', '_', dist_name).lower()}-{version}.tar.gz"


def sdist_url(dist_name: str, version: str) -> str:
    """URL chính thức của sdist trên PyPI (files.pythonhosted.org, đường dẫn theo tên)."""
    name = sdist_filename(dist_name, version)
    return f"https://files.pythonhosted.org/packages/source/{name[0]}/{dist_name}/{name}"


def release_tag() -> str | None:
    """Tag phát hành từ `RELEASE_TAG_ENV`, None nếu không đặt; sai dạng thì `LicenseAuditError`."""
    tag = os.environ.get(RELEASE_TAG_ENV, "").strip()
    if not tag:
        return None
    if not _RELEASE_TAG.fullmatch(tag):
        raise LicenseAuditError(f"{RELEASE_TAG_ENV}={tag!r} không phải tag phát hành (vX.Y.Z[-alpha|-beta])")
    return tag


def sbom_notice_texts(
    key: str, entries: list[tuple[str, str, str, str]]
) -> tuple[list[tuple[str, str, str, list[tuple[str, str]]]], bool]:
    """Văn bản riêng cần in cho thành phần SBOM của gói `key`.

    Trả (các (tên, phiên bản, giấy phép, [(file trong licenses/, nguồn)]) của thành phần cần văn bản
    riêng, có thành phần nào dùng văn bản Apache-2.0 của gói không). Thành phần không thỏa được bằng
    `SBOM_OWNER_TEXT_LICENSES` mà thiếu mục trong `SBOM_NOTICE_TEXTS`, hay thiếu file, thì
    `LicenseAuditError`.
    """
    own: list[tuple[str, str, str, list[tuple[str, str]]]] = []
    uses_owner_text = False
    errors: list[str] = []
    for name, version, expression, _source in entries:
        if _spdx_in(expression, SBOM_OWNER_TEXT_LICENSES):
            uses_owner_text = True
            continue
        texts = SBOM_NOTICE_TEXTS.get((key, name.lower(), version))
        if texts is None:
            errors.append(
                f"{key} (SBOM): {name} {version} ({expression}) cần kèm văn bản giấy phép và dòng bản quyền"
                " riêng; chép từ nguồn đúng phiên bản vào licenses/ rồi thêm vào SBOM_NOTICE_TEXTS"
            )
            continue
        for file_name, _src in texts:
            if not (LICENSES_DIR / file_name).is_file():
                errors.append(f"{key} (SBOM): thiếu văn bản giấy phép {file_name} cho {name} {version}")
        own.append((name, version, expression, list(texts)))
    if errors:
        raise LicenseAuditError("thành phần SBOM thiếu văn bản giấy phép:\n  " + "\n  ".join(errors))
    return own, uses_owner_text


# Văn bản giấy phép của phần mềm bên thứ ba nằm trong CPython mà LICENSE.txt của bản Windows không
# có đủ. Chép nguyên văn vào packaging/pyinstaller/licenses/, theo ĐÚNG phiên bản Python dùng để build
# (thư viện C của bản Windows lấy theo PCbuild/get_externals.bat của cùng tag). Python build khác mọi
# khóa dưới đây thì build dừng: lấy văn bản của tag mới (cùng nguồn) rồi thêm khóa.
# Khóa: phiên bản Python -> các (file trong licenses/, tiêu đề, nguồn đã chép).
_CPYTHON_RST = "https://github.com/python/cpython/blob/{tag}/Doc/license.rst"
_SOURCE_DEPS = "https://github.com/python/cpython-source-deps/blob/{ref}"
CPYTHON_LICENSE_TEXTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "3.12.10": (
        (
            "cpython-3.12.10-incorporated.rst",
            "CPython 3.12.10 - Licenses and Acknowledgements for Incorporated Software",
            _CPYTHON_RST.format(tag="v3.12.10") + " (từ tiêu đề mục này tới hết file)",
        ),
        (
            "xz-5.2.5-COPYING.txt",
            "XZ Utils 5.2.5 (liblzma trong _lzma.pyd) - COPYING",
            _SOURCE_DEPS.format(ref="xz-5.2.5/COPYING") + " (bản xz ghi trong PCbuild/get_externals.bat)",
        ),
    ),
    "3.14.5": (
        (
            "cpython-3.14.5-incorporated.rst",
            "CPython 3.14.5 - Licenses and Acknowledgements for Incorporated Software",
            _CPYTHON_RST.format(tag="v3.14.5") + " (từ tiêu đề mục này tới hết file)",
        ),
        (
            "xz-5.2.5-COPYING.txt",
            "XZ Utils 5.2.5 (liblzma trong _lzma.pyd) - COPYING",
            _SOURCE_DEPS.format(ref="xz-5.2.5/COPYING") + " (bản xz ghi trong PCbuild/get_externals.bat)",
        ),
        (
            "zlib-ng-2.2.4-LICENSE.txt",
            "zlib-ng 2.2.4 (zlib trong python314.dll) - LICENSE.md",
            _SOURCE_DEPS.format(ref="zlib-ng-2.2.4/LICENSE.md")
            + " (bản zlib-ng ghi trong get_externals.bat)",
        ),
        (
            "mpdecimal-4.0.0-COPYRIGHT.txt",
            "mpdecimal 4.0.0 (libmpdec trong _decimal.pyd) - COPYRIGHT.txt",
            _SOURCE_DEPS.format(ref="mpdecimal-4.0.0/COPYRIGHT.txt")
            + " (bản mpdecimal ghi trong get_externals.bat)",
        ),
    ),
}
LICENSES_DIR = Path(__file__).resolve().parent / "licenses"

# Thành phần bên thứ ba nằm trong file của CPython được đóng vào: tiền tố tên file (chữ thường) ->
# (thành phần, giấy phép dạng biểu thức SPDX kiểm theo SPDX_COMPATIBLE, nơi có văn bản trong
# THIRD-PARTY-NOTICES.txt, các regex phải khớp trong văn bản giấy phép của Python để chắc văn bản đó
# thật sự có mặt). "license.rst" là file cpython-<phiên bản>-incorporated.rst ở trên.
PYTHON_EMBEDDED: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    (
        "libssl-",
        "OpenSSL",
        "Apache-2.0",
        "LICENSE.txt của Python (Apache License 2.0); mục OpenSSL của license.rst",
        (r"Apache License", r"(?m)^OpenSSL$"),
    ),
    (
        "libcrypto-",
        "OpenSSL",
        "Apache-2.0",
        "LICENSE.txt của Python (Apache License 2.0); mục OpenSSL của license.rst",
        (r"Apache License", r"(?m)^OpenSSL$"),
    ),
    (
        "libffi-",
        "libffi",
        "MIT",
        "LICENSE.txt của Python; mục libffi của license.rst",
        (r"libffi - Copyright", r"(?m)^libffi$"),
    ),
    ("pyexpat", "expat", "MIT", "mục expat của license.rst", (r"(?m)^expat$",)),
    (
        "_decimal",
        "libmpdec (mpdecimal)",
        "BSD-2-Clause",
        "mục libmpdec của license.rst; COPYRIGHT.txt của mpdecimal nếu bản Python dùng mpdecimal ngoài",
        (r"(?m)^libmpdec$",),
    ),
    (
        "_lzma",
        "liblzma (XZ Utils)",
        "LicenseRef-public-domain",
        "COPYING của XZ Utils",
        (r"liblzma is in the public domain",),
    ),
    ("_bz2", "bzip2/libbzip2", "bzip2-1.0.6", "LICENSE.txt của Python", (r"bzip2/libbzip2",)),
    (
        "_zstd",
        "Zstandard và phần bindings lấy từ pyzstd",
        "BSD-3-Clause",
        "LICENSE.txt của Python (Zstandard); mục Zstandard bindings của license.rst",
        (r"For Zstandard software", r"(?m)^Zstandard bindings$"),
    ),
    (
        "python3",
        "Mã tích hợp trong lõi CPython: zlib (bản 3.14: zlib-ng), Mersenne Twister, SipHash24, "
        "strtod/dtoa, cfuhash, mimalloc (3.13+), GUS (3.14), phần asyncio lấy từ uvloop",
        "Zlib AND BSD-2-Clause AND BSD-3-Clause AND MIT AND LicenseRef-dtoa-notice",
        "các mục tương ứng của license.rst; LICENSE của zlib-ng nếu bản Python dùng zlib-ng",
        (r"(?m)^zlib$", r"(?m)^Mersenne Twister$", r"(?m)^SipHash24$", r"(?m)^strtod and dtoa$"),
    ),
    (
        "vcruntime140",
        "Microsoft Visual C++ Runtime",
        "LicenseRef-MSVC-runtime-system-library",
        "LICENSE.txt của Python (Additional Conditions for this Windows binary build)",
        (r"Microsoft Distributable Code",),
    ),
)

# Ghi chú bắt buộc cho DLL runtime của trình biên dịch đi kèm Python.
VCRUNTIME_NOTE = (
    "vcruntime140.dll và vcruntime140_1.dll là thư viện runtime của trình biên dịch Microsoft Visual C++\n"
    "đã dùng để build CPython. Chúng đi kèm như một phần của runtime Python, được phân phối theo ngoại\n"
    'lệ System Library của GPLv3 (mục 1 của GPLv3) và theo điều kiện "Additional Conditions for this\n'
    'Windows binary build" trong LICENSE.txt của Python.'
)

# ---- Bản GUI: Qt/PySide6 -------------------------------------------------------------------------
# Bản phân phối mang DLL Qt (PySide6-Essentials) và phiên bản Qt mà QT_EMBEDDED đã rà. Nâng PySide6
# thì build dừng (`qt_embedded_files`): rà lại qt_attribution.json của qtbase và pyside-setup, cùng
# qt_attribution.json/REUSE.toml của qtsvg (Qt6Svg.dll) đúng tag mới, chép văn bản vào
# licenses/qt-<phiên bản>/ rồi sửa các hằng dưới đây và bản ghim của PySide6-Essentials, shiboken6
# trong constraints.txt.
QT_OWNER = "pyside6-essentials"
QT_LICENSE_VERSION = "6.12.0"
QT_LICENSES_DIR = f"qt-{QT_LICENSE_VERSION}"
_QT_SUBMODULES = f"https://download.qt.io/official_releases/qt/6.12/{QT_LICENSE_VERSION}/submodules/"
# qtbase: Qt6Core/Gui/Widgets/Network.dll và plugin; qtsvg: Qt6Svg.dll (QSvgRenderer cho icon của ui).
QT_SOURCE_URL = f"{_QT_SUBMODULES}qtbase-everywhere-src-{QT_LICENSE_VERSION}.tar.xz"
QTSVG_SOURCE_URL = f"{_QT_SUBMODULES}qtsvg-everywhere-src-{QT_LICENSE_VERSION}.tar.xz"
# PyPI không có sdist của PySide6-Essentials/shiboken6, nên chỉ tới gói mã nguồn chính thức của Qt.
PYSIDE_SOURCE_URL = (
    f"https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{QT_LICENSE_VERSION}-src/"
    f"pyside-setup-everywhere-src-{QT_LICENSE_VERSION}.tar.xz"
)
_QTBASE = f"https://github.com/qt/qtbase/blob/v{QT_LICENSE_VERSION}/{{}}"
_QTSVG = f"https://github.com/qt/qtsvg/blob/v{QT_LICENSE_VERSION}/{{}}"
_PYSIDE = f"https://github.com/pyside/pyside-setup/blob/v{QT_LICENSE_VERSION}/{{}}"

# Giấy phép được chấp nhận cho thành phần lồng trong Qt/PySide6 (QT_EMBEDDED): SPDX_COMPATIBLE cộng các
# định danh dưới đây, mỗi cái đã có trong dòng Giấy phép của ke_hoach mục 1 (câu về Qt). Chỉ dùng cho
# Qt, không mở rộng cho SBOM hay thư viện C của Python.
QT_SPDX_COMPATIBLE: frozenset[str] = SPDX_COMPATIBLE | frozenset(
    {
        "CC0-1.0",
        "FTL",
        "HPND",
        "HPND-sell-variant",
        "Imlib2",
        "Libpng",
        "libpng-2.0",
        "MIT-open-group",
        "MPL-2.0",  # chỉ dữ liệu Public Suffix List trong Qt6Network.dll
        "Python-2.0",
        "X11",
        "LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception",
        "LicenseRef-ICC-License",
        "LicenseRef-Lcs-Telegraphics",
        "LicenseRef-SHA1-Public-Domain",
    }
)

# File mã máy của Qt/PySide6/shiboken6 đã rà thành phần lồng bên trong (đường dẫn đích, chữ thường,
# dấu "/"). File mã máy nào khác của hai gói (thêm module hay plugin Qt) làm build dừng cho tới khi
# được rà và thêm vào đây. DLL runtime MSVC đi kèm hai gói: xem MSVC_RUNTIME_NOTE.
QT_REVIEWED_FILES: frozenset[str] = frozenset(
    {
        "pyside6/qt6core.dll",
        "pyside6/qt6gui.dll",
        "pyside6/qt6widgets.dll",
        "pyside6/qt6network.dll",
        "pyside6/qt6svg.dll",  # qtsvg: rà theo REUSE.toml (v6.12.0 không có qt_attribution.json)
        "pyside6/plugins/platforms/qwindows.dll",
        "pyside6/plugins/styles/qmodernwindowsstyle.dll",
        "pyside6/qtcore.pyd",
        "pyside6/qtgui.pyd",
        "pyside6/qtwidgets.pyd",
        "pyside6/qtnetwork.pyd",
        "pyside6/qtsvg.pyd",
        "pyside6/pyside6.abi3.dll",
        "shiboken6/shiboken6.abi3.dll",
        "shiboken6/shiboken.pyd",
    }
)
MSVC_RUNTIME_FILES: tuple[str, ...] = ("msvcp140*.dll", "vcruntime140*.dll")
MSVC_RUNTIME_OWNERS: frozenset[str] = frozenset({QT_OWNER, "shiboken6"})
MSVC_RUNTIME_NOTE = (
    "msvcp140*.dll và vcruntime140*.dll trong _internal\\PySide6\\ và _internal\\shiboken6\\ là thư viện\n"
    "runtime của trình biên dịch Microsoft Visual C++ mà bản Qt/PySide6 chính thức đi kèm. Chúng được\n"
    "phân phối theo ngoại lệ System Library của GPLv3 (mục 1 của GPLv3), như DLL runtime đi kèm Python."
)

# Một thành phần lồng trong Qt/PySide6: (mẫu đường dẫn đích của file chứa nó, tên kèm phiên bản, giấy
# phép SPDX theo qt_attribution.json, các (file trong licenses/qt-<ver>/, nguồn đã chép), ghi công bắt
# buộc). Nguồn dữ kiện: qt_attribution.json trong qtbase và pyside-setup đúng tag QT_LICENSE_VERSION,
# đối chiếu chuỗi trong DLL thật. Không ghi thành phần chỉ có trên hệ khác (forkfd, pixman ARM NEON,
# macOS, X11/Wayland) hay nằm trong file không đóng vào (libjpeg của plugin qjpeg, SQLite của QtSql,
# libdbus của QtDBus).
# qtsvg v6.12.0 (Qt6Svg.dll) không có qt_attribution.json và không có src/3rdparty/; thành phần bên thứ ba
# duy nhất được khai là src/svg/REUSE.toml (và licenseRule.json): qsvghandler.cpp có thêm
# HPND-sell-variant, "Copyright 2002 USC Information Sciences Institute" (mã gốc XSVG). Đã kiểm 30/10:
# văn bản qsvghandler.cpp ở tag đó không còn chuỗi nào của XSVG (mã cung tròn nằm ở Qt6Gui, mục XSVG
# dưới đây), nhưng vẫn ghi theo khai báo của chính qtsvg vì không rõ thì không bỏ.
type QtEmbedded = tuple[str, str, str, tuple[tuple[str, str], ...], str]


def _qt(path: str, name: str) -> tuple[str, str]:
    """(file trong licenses/qt-<ver>/, URL nguồn trong qtbase đúng tag)."""
    return (name, _QTBASE.format(path))


def _qtsvg(path: str, name: str) -> tuple[str, str]:
    """(file trong licenses/qt-<ver>/, URL nguồn trong qtsvg đúng tag)."""
    return (name, _QTSVG.format(path))


_CC0 = _qt("LICENSES/CC0-1.0.txt", "CC0-1.0.txt")
_APACHE = _qt("LICENSES/Apache-2.0.txt", "Apache-2.0.txt")
_UNICODE = _qt("LICENSES/Unicode-3.0.txt", "Unicode-3.0.txt")
_FREETYPE = _qt("src/3rdparty/freetype/LICENSE.txt", "freetype-LICENSE.txt")
_FREETYPE_CREDIT = (
    "Portions of this software are copyright © 2025 The FreeType Project (www.freetype.org). "
    "All rights reserved."
)
_CORE, _GUI, _NETWORK = "pyside6/qt6core.dll", "pyside6/qt6gui.dll", "pyside6/qt6network.dll"
QT_EMBEDDED: tuple[QtEmbedded, ...] = (
    (_CORE, "zlib 1.3.2", "Zlib", (_qt("src/3rdparty/zlib/LICENSE", "zlib-LICENSE.txt"),), ""),
    (
        _CORE,
        "PCRE2 10.48",
        "LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception",
        (_qt("src/3rdparty/pcre2/LICENCE.md", "pcre2-LICENCE.md"),),
        "",
    ),
    (
        _CORE,
        "PCRE2 - Stack-less Just-In-Time Compiler 10.48",
        "BSD-2-Clause",
        (_qt("src/3rdparty/pcre2/LICENSE-SLJIT", "pcre2-LICENSE-SLJIT.txt"),),
        "",
    ),
    (
        _CORE,
        "double-conversion 3.4.0",
        "BSD-3-Clause",
        (_qt("src/3rdparty/double-conversion/LICENSE", "double-conversion-LICENSE.txt"),),
        "",
    ),
    (
        _CORE,
        "Easing Equations by Robert Penner",
        "BSD-3-Clause",
        (_qt("src/3rdparty/easing/LICENSE", "easing-LICENSE.txt"),),
        "",
    ),
    (_CORE, "TinyCBOR 7.0", "MIT", (_qt("src/3rdparty/tinycbor/LICENSE", "tinycbor-LICENSE.txt"),), ""),
    (
        _CORE,
        "BLAKE2 (reference implementation)",
        "CC0-1.0 OR Apache-2.0",
        (_qt("src/3rdparty/blake2/COPYING", "blake2-COPYING.txt"),),
        "",
    ),
    (_CORE, "MD4", "CC0-1.0", (_CC0,), ""),
    (_CORE, "MD5", "CC0-1.0", (_CC0,), ""),
    (
        _CORE,
        "Secure Hash Algorithm SHA-1",
        "LicenseRef-SHA1-Public-Domain",
        (_qt("LICENSES/LicenseRef-SHA1-Public-Domain.txt", "LicenseRef-SHA1-Public-Domain.txt"),),
        "",
    ),
    (
        _CORE,
        "SHA-3 - brg_endian 1.0.0",
        "BSD-2-Clause",
        (_qt("src/3rdparty/sha3/BRG_ENDIAN_LICENSE", "sha3-BRG_ENDIAN_LICENSE.txt"),),
        "",
    ),
    (
        _CORE,
        "SHA-3 - Keccak 3.2",
        "CC0-1.0",
        (_qt("src/3rdparty/sha3/CC0_LICENSE", "sha3-CC0_LICENSE.txt"),),
        "",
    ),
    (
        _CORE,
        "Secure Hash Algorithms SHA-384 and SHA-512 (RFC 6234)",
        "BSD-3-Clause",
        (_qt("src/3rdparty/rfc6234/LICENSE", "rfc6234-LICENSE.txt"),),
        "",
    ),
    (_CORE, "SipHash", "CC0-1.0", (_CC0,), ""),
    (_CORE, "tl::expected", "CC0-1.0", (_CC0,), ""),
    (_CORE, "Apache Tika MimeType Definitions", "Apache-2.0", (_APACHE,), ""),
    (_CORE, "Unicode Character Database (UCD)", "Unicode-3.0", (_UNICODE,), ""),
    (_CORE, "Unicode CLDR v48.2", "Unicode-3.0", (_UNICODE,), ""),
    (_GUI, "FreeType 2.14.3", "FTL OR GPL-2.0-only", (_FREETYPE,), _FREETYPE_CREDIT),
    (
        _GUI,
        "FreeType 2 - zlib",
        "Zlib",
        (_qt("src/3rdparty/freetype/ZLIB-LICENSE.txt", "freetype-ZLIB-LICENSE.txt"),),
        "",
    ),
    (
        _GUI,
        "FreeType 2 - BDF",
        "MIT",
        (_qt("src/3rdparty/freetype/BDF-LICENSE.txt", "freetype-BDF-LICENSE.txt"),),
        "",
    ),
    (
        _GUI,
        "FreeType 2 - PCF",
        "MIT AND MIT-open-group",
        (_qt("src/3rdparty/freetype/PCF-LICENSE.txt", "freetype-PCF-LICENSE.txt"),),
        "",
    ),
    (_GUI, "Anti-aliasing rasterizer from FreeType 2", "FTL OR GPL-2.0-only", (_FREETYPE,), _FREETYPE_CREDIT),
    (
        _GUI,
        "HarfBuzz-NG 14.5.0",
        "MIT",
        (_qt("src/3rdparty/harfbuzz-ng/COPYING", "harfbuzz-ng-COPYING.txt"),),
        "",
    ),
    (
        _GUI,
        "libpng 1.6.58",
        "Libpng AND libpng-2.0",
        (_qt("src/3rdparty/libpng/LICENSE", "libpng-LICENSE.txt"),),
        "",
    ),
    (_GUI, "MD4C 0.5.3", "MIT", (_qt("src/3rdparty/md4c/LICENSE.md", "md4c-LICENSE.md"),), ""),
    (_GUI, "Emoji Segmenter 0.4.0", "Apache-2.0", (_APACHE,), ""),
    (
        _GUI,
        "D3D12 Memory Allocator 3.1.0",
        "MIT",
        (_qt("src/3rdparty/D3D12MemoryAllocator/LICENSE.txt", "D3D12MemoryAllocator-LICENSE.txt"),),
        "",
    ),
    (
        _GUI,
        "Vulkan Memory Allocator 3.3.0",
        "MIT",
        (_qt("src/3rdparty/VulkanMemoryAllocator/LICENSE.txt", "VulkanMemoryAllocator-LICENSE.txt"),),
        "",
    ),
    (
        _GUI,
        "sRGB color profile icc file",
        "LicenseRef-ICC-License",
        (_qt("src/3rdparty/icc/LICENSE.txt", "icc-LICENSE.txt"),),
        "",
    ),
    (
        _GUI,
        "OpenGL Headers, OpenGL ES 2 Headers",
        "MIT",
        (_qt("src/gui/opengl/LICENSE.KHRONOS.txt", "LICENSE.KHRONOS.txt"),),
        "",
    ),
    (
        _GUI,
        "Smooth Scaling Algorithm (QImage)",
        "BSD-2-Clause AND Imlib2",
        (_qt("src/gui/painting/LICENSE.QIMAGETRANSFORM.txt", "LICENSE.QIMAGETRANSFORM.txt"),),
        "",
    ),
    (
        _GUI,
        "X Server helper (QRegion)",
        "X11 AND HPND",
        (_qt("src/gui/painting/LICENSE.XCONSORTIUM.txt", "LICENSE.XCONSORTIUM.txt"),),
        "",
    ),
    (
        _GUI,
        "Mipmap generator for D3D12 (MiniEngine)",
        "MIT",
        (_qt("src/gui/rhi/LICENSE.MiniEngine.txt", "LICENSE.MiniEngine.txt"),),
        "",
    ),
    (
        _GUI,
        "Adobe Glyph List For New Fonts 1.7",
        "BSD-3-Clause",
        (_qt("src/gui/text/LICENSE.AGLFN.txt", "LICENSE.AGLFN.txt"),),
        "",
    ),
    (
        _GUI,
        "Vulkan API Registry 1.4.308",
        "Apache-2.0 OR MIT",
        (_qt("src/gui/vulkan/LICENSE.txt", "vulkan-LICENSE.txt"),),
        "",
    ),
    (_GUI, "XSVG", "HPND-sell-variant", (_qt("src/gui/util/LICENSE.XSVG.txt", "LICENSE.XSVG.txt"),), ""),
    (
        _GUI,
        "WebGradients",
        "MIT",
        (_qt("util/gradientgen/LICENSE.WEBGRADIENTS.txt", "LICENSE.WEBGRADIENTS.txt"),),
        "",
    ),
    (
        _NETWORK,
        "The Public Suffix List (dữ liệu)",
        "MPL-2.0",
        (_qt("src/3rdparty/libpsl/PSL-LICENSE.txt", "libpsl-PSL-LICENSE.txt"),),
        "",
    ),
    (
        _NETWORK,
        "libpsl (tra cứu Public Suffix List)",
        "BSD-3-Clause",
        (_qt("src/3rdparty/libpsl/src/LICENSE.chromium", "libpsl-LICENSE.chromium.txt"),),
        "",
    ),
    (
        "pyside6/qt6svg.dll",
        "XSVG (USC Information Sciences Institute), theo REUSE.toml của qtsvg cho qsvghandler.cpp",
        "HPND-sell-variant",
        (_qtsvg("LICENSES/HPND-sell-variant.txt", "qtsvg-HPND-sell-variant.txt"),),
        "",
    ),
    (
        "pyside6/plugins/platforms/qwindows.dll",
        "Wintab API (header)",
        "LicenseRef-Lcs-Telegraphics",
        (_qt("LICENSES/LicenseRef-Lcs-Telegraphics.txt", "LicenseRef-Lcs-Telegraphics.txt"),),
        "",
    ),
    (
        "shiboken6/shiboken6.abi3.dll",
        "Mã lấy từ Python 3.7.0 (bufferprocs_py37, shibokensupport/signature)",
        "Python-2.0",
        (
            (
                "shiboken6-PSF-3.7.0.txt",
                _PYSIDE.format(
                    "sources/shiboken6/shibokenmodule/files.dir/shibokensupport/signature/PSF-3.7.0.txt"
                ),
            ),
        ),
        "",
    ),
)

# Văn bản giấy phép thay cho file trong dist-info: (ghi chú, các (file trong licenses/, tiêu đề, nguồn)).
# Dist-info của PySide6-Essentials và shiboken6 chỉ có LicenseRef-Qt-Commercial.txt; bản build dùng nhánh
# LGPL-3.0-only, nên kèm văn bản LGPL-3.0 (văn bản GPL-3.0 mà LGPL-3.0 dẫn tới là file LICENSE).
_LGPL3 = (
    (
        f"{QT_LICENSES_DIR}/LGPL-3.0-only.txt",
        "GNU Lesser General Public License v3.0 (LGPL-3.0-only)",
        _QTBASE.format("LICENSES/LGPL-3.0-only.txt"),
    ),
)
_LGPL3_NOTE = (
    "Dùng theo nhánh LGPL-3.0-only của biểu thức trên. LGPL-3.0 bổ sung cho GPL-3.0: văn bản GPL-3.0 là\n"
    "file LICENSE cùng thư mục. Cách thay thư viện và nơi lấy mã nguồn: SOURCE.txt."
)
PACKAGE_LICENSE_TEXTS: dict[str, tuple[str, tuple[tuple[str, str, str], ...]]] = {
    QT_OWNER: (
        _LGPL3_NOTE
        + "\nMã nguồn Qt: "
        + QT_SOURCE_URL
        + " (Qt6Core, Qt6Gui, Qt6Widgets, Qt6Network và plugin) ; "
        + QTSVG_SOURCE_URL
        + " (Qt6Svg)",
        _LGPL3,
    ),
    "shiboken6": (_LGPL3_NOTE, _LGPL3),
}
# Dòng "Mã nguồn:" của gói không có sdist trên PyPI: trỏ tới gói mã nguồn chính thức thay link PyPI.
PACKAGE_SOURCE_URLS: dict[str, str] = {QT_OWNER: PYSIDE_SOURCE_URL, "shiboken6": PYSIDE_SOURCE_URL}


def qt_embedded_files(components: dict[str, Component]) -> list[tuple[QtEmbedded, list[str]]]:
    """Thành phần lồng trong Qt/PySide6 có mặt trong bản build, kèm file chứa nó (đường dẫn đích).

    Không có PySide6 thì trả rỗng. Dừng với `LicenseAuditError` khi: phiên bản PySide6 khác
    `QT_LICENSE_VERSION`; có file mã máy (.dll/.pyd) của PySide6/shiboken6 chưa rà
    (`QT_REVIEWED_FILES`, trừ DLL runtime MSVC); giấy phép một thành phần ngoài `QT_SPDX_COMPATIBLE`;
    thiếu file văn bản trong licenses/.
    """
    owned = [comp for key, comp in components.items() if key in MSVC_RUNTIME_OWNERS]
    if not owned:
        return []
    errors: list[str] = []
    for comp in owned:
        if comp.version != QT_LICENSE_VERSION:
            errors.append(
                f"{comp.name} {comp.version}: thành phần lồng trong Qt mới rà cho {QT_LICENSE_VERSION}"
                " (QT_EMBEDDED); rà lại qt_attribution.json của bản mới"
            )
    dests = sorted({f.replace("\\", "/").lower() for comp in owned for f in comp.files})
    for dest in dests:
        base = dest.rsplit("/", 1)[-1]
        if not dest.endswith((".dll", ".pyd")) or dest in QT_REVIEWED_FILES:
            continue
        if any(fnmatch.fnmatchcase(base, pattern) for pattern in MSVC_RUNTIME_FILES):
            continue
        errors.append(f"{dest}: file mã máy của Qt/PySide6 chưa rà thành phần lồng (QT_REVIEWED_FILES)")
    found: list[tuple[QtEmbedded, list[str]]] = []
    for entry in QT_EMBEDDED:
        pattern, name, lic, texts, _credit = entry
        files = [d for d in dests if fnmatch.fnmatchcase(d, pattern)]
        if not files:
            continue
        if not _spdx_in(lic, QT_SPDX_COMPATIBLE):
            errors.append(f"Qt: {name} giấy phép {lic!r} chưa duyệt")
        for file_name, _source in texts:
            if not (LICENSES_DIR / QT_LICENSES_DIR / file_name).is_file():
                errors.append(f"Qt: thiếu văn bản giấy phép {QT_LICENSES_DIR}/{file_name} cho {name}")
        found.append((entry, files))
    if errors:
        raise LicenseAuditError("thành phần Qt/PySide6 chưa duyệt:\n  " + "\n  ".join(errors))
    return found


_LICENSE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.IGNORECASE)
_SEPARATOR = "=" * 78
_BASE_LIBRARY = "base_library.zip"


class LicenseAuditError(Exception):
    """Bản build chứa thứ chưa duyệt được giấy phép; build phải dừng."""


@dataclass(frozen=True)
class Edition:
    """Bản build: tên hiện trong THIRD-PARTY-NOTICES.txt/SOURCE.txt và tên file exe (chứa bootloader)."""

    label: str
    exe_name: str


CLI_EDITION = Edition("bản CLI", "teleport.exe")
GUI_EDITION = Edition("bản GUI", "Teleport.exe")


@dataclass
class Component:
    """Một thành phần đóng vào: gói Python (khóa là tên đã chuẩn hóa), "python", hay tài sản
    (`asset:<key>`, `asset` là mục SOURCE_ASSETS, `license_path` là file nguồn của giấy phép đi kèm)."""

    key: str
    name: str
    version: str
    license: str
    files: list[str] = field(default_factory=list)
    asset: SourceAsset | None = None
    license_path: str | None = None


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _norm_path(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(path))


def declared_license(dist: md.Distribution) -> str:
    """Giấy phép theo metadata: License-Expression, rồi License, rồi các classifier License."""
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    text = meta.get("License")
    if text and text.strip() and text.strip().upper() != "UNKNOWN":
        return " ".join(text.split())
    classifiers = [c for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return "; ".join(classifiers)


def spdx_compatible(expression: str) -> bool:
    """Biểu thức SPDX có tương thích GPLv3 không, theo `SPDX_COMPATIBLE` (OR: một nhánh; AND: mọi vế)."""
    return _spdx_in(expression, SPDX_COMPATIBLE)


def _spdx_in(expression: str, allowed: frozenset[str]) -> bool:
    """Như `spdx_compatible` nhưng theo tập định danh `allowed` (Qt dùng `QT_SPDX_COMPATIBLE`)."""
    tokens = re.findall(r"\(|\)|[^\s()]+", expression)
    merged: list[str] = []
    i = 0
    while i < len(tokens):  # gộp "X WITH Y" thành một định danh
        if i + 2 < len(tokens) and tokens[i + 1] == "WITH":
            merged.append(f"{tokens[i]} WITH {tokens[i + 2]}")
            i += 3
        else:
            merged.append(tokens[i])
            i += 1
    pos = 0

    def parse_or() -> bool:
        nonlocal pos
        result = parse_and()
        while pos < len(merged) and merged[pos] == "OR":
            pos += 1
            right = parse_and()
            result = result or right
        return result

    def parse_and() -> bool:
        nonlocal pos
        result = parse_atom()
        while pos < len(merged) and merged[pos] == "AND":
            pos += 1
            right = parse_atom()
            result = result and right
        return result

    def parse_atom() -> bool:
        nonlocal pos
        if pos >= len(merged):
            raise LicenseAuditError(f"biểu thức SPDX không hợp lệ: {expression!r}")
        token = merged[pos]
        pos += 1
        if token == "(":
            result = parse_or()
            if pos >= len(merged) or merged[pos] != ")":
                raise LicenseAuditError(f"biểu thức SPDX không hợp lệ: {expression!r}")
            pos += 1
            return result
        return token in allowed

    result = parse_or()
    if pos != len(merged):
        raise LicenseAuditError(f"biểu thức SPDX không hợp lệ: {expression!r}")
    return result


def _owner_index() -> dict[str, md.Distribution]:
    """Đường dẫn file (đã chuẩn hóa) -> bản phân phối có file đó trong RECORD."""
    index: dict[str, md.Distribution] = {}
    for dist in md.distributions():
        for entry in dist.files or []:
            index.setdefault(_norm_path(Path(str(dist.locate_file(entry)))), dist)
    return index


def _is_under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def _license_files(dist: md.Distribution) -> list[Path]:
    found = []
    for entry in dist.files or []:
        parts = Path(str(entry)).parts
        in_dist_info = any(p.endswith(".dist-info") for p in parts[:-1])
        if in_dist_info and ("licenses" in parts or _LICENSE_FILE.match(parts[-1])):
            found.append(Path(str(dist.locate_file(entry))))
    return sorted(found)


def _sbom_components(dist: md.Distribution) -> list[tuple[str, str, str, str]]:
    """(tên, phiên bản, giấy phép SPDX, nguồn dữ kiện) cho từng thành phần trong SBOM CycloneDX."""
    components = []
    for entry in dist.files or []:
        parts = Path(str(entry)).parts
        if "sboms" not in parts or not parts[-1].endswith(".json"):
            continue
        data = json.loads(Path(str(dist.locate_file(entry))).read_text(encoding="utf-8"))
        for comp in data.get("components", []):
            name, version = comp.get("name", "?"), comp.get("version", "?")
            licenses = []
            for item in comp.get("licenses", []):
                lic = item.get("expression") or item.get("license", {}).get("id")
                if not lic:
                    raise LicenseAuditError(f"SBOM của {dist.name}: {name} có giấy phép không phải SPDX")
                licenses.append(lic)
            source = f"SBOM {parts[-1]}"
            if not licenses:
                known = SBOM_KNOWN_LICENSES.get(name.lower())
                major = int(version.split(".")[0]) if version.split(".")[0].isdigit() else -1
                if known is None or major < known[0]:
                    raise LicenseAuditError(f"SBOM của {dist.name}: {name} {version} không ghi giấy phép")
                licenses = [known[1]]
                source = f"SBOM {parts[-1]} không ghi giấy phép; theo {known[2]}"
            expression = " AND ".join(f"({lic})" if " " in lic else lic for lic in licenses)
            components.append((name, version, expression, source))
    return components


def _python_license_file(base_prefix: str | None = None) -> Path:
    """LICENSE.txt của bản Python dùng để build (`base_prefix` mặc định là `sys.base_prefix`)."""
    base = Path(sys.base_prefix if base_prefix is None else base_prefix)
    candidates = [
        base / "LICENSE.txt",
        base / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "LICENSE.txt",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise LicenseAuditError(f"không tìm thấy LICENSE.txt của Python trong {base}")


def _git(repo_dir: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo_dir), *args], check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return out.stdout.strip()


def _python_dirs(base_prefix: str | None = None) -> tuple[str, list[str], list[str]]:
    """(base_prefix, thư mục thư viện chuẩn, thư mục site-packages) của bản Python dùng để build.

    `base_prefix` mặc định là `sys.base_prefix`, đọc lúc gọi; test truyền thư mục giả vào đây.
    """
    base = sys.base_prefix if base_prefix is None else base_prefix
    base_vars = {"base": base, "platbase": base, "installed_base": base, "installed_platbase": base}
    base_paths = sysconfig.get_paths(vars=base_vars)
    stdlib = [
        os.path.join(base, "DLLs"),
        os.path.join(base, "Lib"),
        base_paths["stdlib"],
        base_paths["platstdlib"],
    ]
    site_dirs = [base_paths["purelib"], base_paths["platlib"]]
    current = sysconfig.get_paths()
    site_dirs += [current["purelib"], current["platlib"]]
    with contextlib.suppress(AttributeError):  # site.getsitepackages không có trong vài môi trường cũ
        site_dirs += site.getsitepackages() + site.getsitepackages([base])
    # Trên Windows site.getsitepackages() trả cả chính prefix (ví dụ C:\Python314) bên cạnh
    # Lib\site-packages; chỉ giữ thư mục site-packages thật, nếu không mọi file Python đều bị loại.
    site_dirs = [p for p in site_dirs if Path(p).name.lower() in {"site-packages", "dist-packages"}]
    return (
        _norm_path(base),
        sorted({_norm_path(p) for p in stdlib}),
        sorted({_norm_path(p) for p in site_dirs}),
    )


# File được nhận là của Python khi nằm thẳng trong base_prefix (mẫu tên, so chữ thường). Mọi file khác
# ở gốc base_prefix là file lạ. python.exe/pythonw.exe không có ở đây vì bản onedir không đóng chúng.
PYTHON_ROOT_FILES: tuple[str, ...] = ("python3*.dll", "vcruntime140*.dll")

# Universal CRT (mẫu tên file đích, so chữ thường): thành phần của Windows 10 trở lên nên không đóng vào.
# PyInstaller cố ý gom các DLL này khi tìm thấy chúng ngoài System32, ví dụ trong thư mục bin của một
# JDK nằm trên PATH, nên bản sao lấy từ công cụ không liên quan lọt vào bản build. Spec lọc chúng khỏi
# `Analysis.binaries` bằng `drop_ucrt` TRƯỚC `check`; `check` không nhận chúng là file đã biết, nên bản
# sao nào lọt qua bộ lọc vẫn làm build dừng như mọi file lạ. Chỉ đúng ba họ này, không mở rộng.
UCRT_FILES: tuple[str, ...] = ("api-ms-win-core-*.dll", "api-ms-win-crt-*.dll", "ucrtbase.dll")


def drop_ucrt(
    toc: Iterable[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Bỏ khỏi TOC các file Universal CRT (`UCRT_FILES`, theo tên file đích, không phân biệt hoa thường).

    Trả (TOC còn lại, giữ nguyên thứ tự; tên đích đã bỏ).
    """
    kept: list[tuple[str, str, str]] = []
    dropped: list[str] = []
    for entry in toc:
        name = re.split(r"[\\/]", entry[0])[-1].lower()
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in UCRT_FILES):
            dropped.append(entry[0])
        else:
            kept.append(entry)
    return kept, dropped


def drop_files(
    toc: Iterable[tuple[str, str, str]], patterns: Iterable[str]
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Bỏ khỏi TOC các file có đường dẫn đích khớp một mẫu trong `patterns`.

    So bằng `fnmatch` trên đường dẫn đích chữ thường, dấu `/` (ví dụ `pyside6/plugins/tls/*`). Trả
    (TOC còn lại, giữ nguyên thứ tự; tên đích đã bỏ). Dùng cho phần Qt không dùng (`teleport-gui.spec`).
    """
    pats = tuple(p.lower() for p in patterns)
    kept: list[tuple[str, str, str]] = []
    dropped: list[str] = []
    for entry in toc:
        dest = entry[0].replace("\\", "/").lower()
        if any(fnmatch.fnmatchcase(dest, pattern) for pattern in pats):
            dropped.append(entry[0])
        else:
            kept.append(entry)
    return kept, dropped


def _is_python_file(path: str, python_dirs: tuple[str, list[str], list[str]]) -> bool:
    """File thuộc chính bản Python (PSF-2.0 và thành phần ở PYTHON_EMBEDDED) hay không.

    `path` đã chuẩn hóa bằng `_norm_path`; `python_dirs` là kết quả của `_python_dirs`. Chỉ nhận: file
    nằm thẳng trong `base_prefix` có tên khớp `PYTHON_ROOT_FILES`, file trong `DLLs/` và trong thư
    viện chuẩn `Lib/`. Mọi thứ trong site-packages (CI không dùng venv nên site-packages nằm dưới
    `base_prefix`) mà không có RECORD nhận là file lạ, build phải dừng.
    """
    base, stdlib, site_dirs = python_dirs
    parts = {part.lower() for part in Path(path).parts}
    if parts & {"site-packages", "dist-packages"}:
        return False
    if any(_is_under(path, root) for root in site_dirs):
        return False
    if os.path.dirname(path) == base:
        name = os.path.basename(path).lower()
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in PYTHON_ROOT_FILES)
    return any(_is_under(path, root) for root in stdlib)


def _localpyc_source(name: str, path: str, base_prefix: str | None = None) -> str | None:
    """Nguồn của module khởi động mà PYZ dịch sẵn vào `<workpath>/localpycs/` (PYZ.dependencies).

    Đó là module loader của PyInstaller (`PyInstaller/loader/pyimod0x_*.py`) và `struct` của thư viện
    chuẩn. Trả đường dẫn file nguồn để phân loại như mọi file khác; không nhận ra thì None (file lạ).
    """
    if Path(path).parent.name != "localpycs" or not path.endswith(".pyc"):
        return None
    base = sys.base_prefix if base_prefix is None else base_prefix
    loader = md.distribution("pyinstaller").locate_file(f"PyInstaller/loader/{name}.py")
    base_vars = {"installed_base": base, "base": base}
    candidates = [Path(str(loader)), Path(sysconfig.get_paths(vars=base_vars)["stdlib"]) / f"{name}.py"]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def collect_components(
    toc: Iterable[tuple[str, str, str]],
    *,
    repo_dir: Path,
    base_prefix: str | None = None,
    edition: Edition = CLI_EDITION,
) -> tuple[dict[str, Component], dict[str, list[str]]]:
    """Phân loại mọi file trong TOC theo thành phần.

    Trả (thành phần, file của CPython có chứa thành phần bên thứ ba theo `PYTHON_EMBEDDED`). File có
    nguồn dưới `repo_dir/src/teleport/ui/assets/` xếp vào thành phần tài sản `asset:<key>` trước mọi
    nhánh khác (RECORD của bản cài editable hay thường đều có thể chứa chúng); không khớp mục nào của
    `SOURCE_ASSETS` thì `LicenseAuditError`.
    """
    owners = _owner_index()
    # Mã của dự án: src/ (gói teleport) và packaging/ (launcher). Không lấy cả gốc repo vì venv
    # build có thể nằm trong repo (.venv/), file của venv phải tra theo RECORD.
    src_root = _norm_path(repo_dir / "src")
    assets_root = _norm_path(repo_dir / "src" / ASSETS_ROOT)
    own_roots = [src_root, _norm_path(repo_dir / "packaging")]
    python_dirs = _python_dirs(base_prefix)
    components: dict[str, Component] = {}
    python_files: dict[str, list[str]] = {}  # tiền tố trong PYTHON_EMBEDDED -> tên file đã đóng vào
    unknown: list[str] = []
    stray_assets: list[str] = []

    def add_asset(path: str, dest: str, src: str) -> None:
        rel = os.path.relpath(path, src_root).replace(os.sep, "/")
        match = _match_asset(rel)
        if match is None:
            stray_assets.append(f"{dest} <- {src}")
            return
        asset, is_license = match
        key = f"asset:{asset.key}"
        comp = components.get(key)
        if comp is None:
            comp = Component(key, asset.name, asset.version, asset.license, asset=asset)
            components[key] = comp
        comp.files.append(dest)
        if is_license:
            comp.license_path = src

    def add(dist: md.Distribution, dest: str) -> None:
        key = _normalize(dist.name)
        comp = components.get(key)
        if comp is None:
            comp = Component(key, dist.name, dist.version, declared_license(dist))
            components[key] = comp
        comp.files.append(dest)

    for dest, src, _typecode in toc:
        if not src:
            continue
        path = _norm_path(src)
        source = _localpyc_source(dest, path, base_prefix)
        if source is not None:
            path = _norm_path(source)
        # Tài sản trước tiên: chúng nằm trong src/ của dự án nhưng không theo giấy phép của dự án.
        if _is_under(path, assets_root) and path != assets_root:
            add_asset(path, dest, src)
        # Tra RECORD trước: site-packages có thể nằm trong thư mục cài Python (không dùng venv).
        elif path in owners:
            add(owners[path], dest)
        elif any(_is_under(path, root) for root in own_roots):
            add(md.distribution("zero-cloud-lan-teleport"), dest)
        elif _is_python_file(path, python_dirs) or (
            dest == _BASE_LIBRARY and os.path.basename(path) == _BASE_LIBRARY
        ):
            # base_library.zip do PyInstaller dựng trong workpath từ thư viện chuẩn của Python.
            components.setdefault(
                "python",
                Component("python", "Python (CPython)", sys.version.split()[0], "PSF-2.0"),
            ).files.append(dest)
            base = os.path.basename(path)
            for prefix, *_rest in PYTHON_EMBEDDED:
                # Chỉ file mã máy (.pyd/.dll); module .py trùng tiền tố (ví dụ _zstdfile.py) không tính.
                if base.lower().startswith(prefix) and base.lower().endswith((".pyd", ".dll")):
                    python_files.setdefault(prefix, []).append(base)
        else:
            unknown.append(f"{dest} <- {src}")
    if stray_assets:
        raise LicenseAuditError(
            f"file trong src/{ASSETS_ROOT}/ không thuộc mục nào của SOURCE_ASSETS (thêm nguồn, commit"
            " ghim và giấy phép trước khi đóng vào):\n  " + "\n  ".join(sorted(stray_assets))
        )
    if unknown:
        raise LicenseAuditError(
            "không xác định được file sau thuộc gói nào:\n  " + "\n  ".join(sorted(unknown))
        )
    # Bootloader nhúng trong exe không nằm trong TOC.
    if "pyinstaller" not in components:
        add(md.distribution("pyinstaller"), f"{edition.exe_name} (bootloader)")
    return components, {prefix: sorted(set(files)) for prefix, files in python_files.items()}


def audit(
    components: dict[str, Component], python_files: dict[str, list[str]]
) -> dict[str, list[tuple[str, str, str, str]]]:
    """Dừng build nếu có gì chưa duyệt; trả thành phần SBOM của từng gói (đã kiểm).

    Tài sản (`comp.asset`) kiểm theo `ASSET_LICENSES` và phải đóng kèm file giấy phép của nó; không
    tra `APPROVED`, metadata hay SBOM (chúng không phải bản phân phối Python).
    """
    errors = []
    sboms: dict[str, list[tuple[str, str, str, str]]] = {}
    for key, comp in sorted(components.items()):
        if key == "python":
            continue
        if comp.asset is not None:
            if not _spdx_in(comp.license, ASSET_LICENSES):
                errors.append(f"{comp.name} ({key}): giấy phép {comp.license!r} ngoài ASSET_LICENSES")
            if comp.license_path is None:
                errors.append(f"{comp.name} ({key}): thiếu file giấy phép đi kèm {comp.asset.license_file}")
            continue
        if key.startswith("asset:"):
            errors.append(f"{comp.name} ({key}): khóa tài sản nhưng không có mục SOURCE_ASSETS")
            continue
        expected = APPROVED.get(key)
        if expected is None:
            errors.append(f"{comp.name} {comp.version} ({comp.license}): chưa có trong APPROVED")
        elif comp.license != expected:
            errors.append(
                f"{comp.name} {comp.version}: giấy phép {comp.license!r} khác bản đã duyệt {expected!r}"
            )
        entries = _sbom_components(md.distribution(comp.name))
        for name, version, expression, _source in entries:
            if not spdx_compatible(expression):
                errors.append(f"{comp.name} (SBOM): {name} {version} giấy phép {expression!r} chưa duyệt")
        if entries:
            sboms[key] = entries
    for prefix, name, lic, _where, _markers in PYTHON_EMBEDDED:
        if prefix in python_files and not spdx_compatible(lic):
            errors.append(f"Python: {name} giấy phép {lic!r} chưa duyệt")
    if errors:
        raise LicenseAuditError("giấy phép chưa duyệt:\n  " + "\n  ".join(errors))
    return sboms


_SOURCE_URL_LABELS = frozenset(
    {"source", "source code", "sourcecode", "repository", "github", "homepage", "home"}
)


def _project_urls(dist: md.Distribution) -> list[str]:
    """Nơi lấy mã nguồn: trang file của đúng phiên bản trên PyPI (có sdist) + kho mã trong metadata."""
    urls = [f"https://pypi.org/project/{dist.name}/{dist.version}/#files"]
    for entry in dist.metadata.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in _SOURCE_URL_LABELS and url.strip():
            urls.append(url.strip())
    home = dist.metadata.get("Home-page")
    if home and home.strip():
        urls.append(home.strip())
    return list(dict.fromkeys(urls))


def _cpython_license_texts() -> list[tuple[str, str, str]]:
    """(tiêu đề, nguồn, nội dung) của văn bản giấy phép CPython bổ sung, đúng phiên bản đang build."""
    version = platform.python_version()
    entries = CPYTHON_LICENSE_TEXTS.get(version)
    if entries is None:
        raise LicenseAuditError(
            f"chưa có văn bản giấy phép phần mềm tích hợp của CPython {version} trong "
            "packaging/pyinstaller/licenses/ (xem CPYTHON_LICENSE_TEXTS)"
        )
    return [
        (title, source, (LICENSES_DIR / name).read_text(encoding="utf-8")) for name, title, source in entries
    ]


def _python_library_versions() -> dict[str, str]:
    """Phiên bản thư viện C trong bản Python đang build (cùng các file sẽ được đóng vào)."""
    versions = {"libssl-": ssl.OPENSSL_VERSION, "libcrypto-": ssl.OPENSSL_VERSION}
    with contextlib.suppress(ImportError):
        import pyexpat

        versions["pyexpat"] = pyexpat.EXPAT_VERSION
    with contextlib.suppress(ImportError):
        import decimal

        versions["_decimal"] = f"libmpdec {decimal.__libmpdec_version__}"
    with contextlib.suppress(ImportError):
        import zlib

        zlib_ng = getattr(zlib, "ZLIBNG_VERSION", None)
        versions["python3"] = f"zlib-ng {zlib_ng}" if zlib_ng else f"zlib {zlib.ZLIB_RUNTIME_VERSION}"
    with contextlib.suppress(ImportError):
        import _zstd

        versions["_zstd"] = f"zstd {_zstd.zstd_version}"
    return versions


def _asset_notice(comp: Component) -> list[str]:
    """Phần riêng của một thành phần tài sản trong THIRD-PARTY-NOTICES.txt, sau dòng tên và "Giấy phép:":
    nguồn, số file, văn bản giấy phép nguyên văn từ file giấy phép đã đóng kèm (không đọc metadata)."""
    asset = comp.asset
    if asset is None or comp.license_path is None:
        raise LicenseAuditError(f"{comp.name}: thiếu file giấy phép đi kèm")
    folder, _, license_name = asset.license_file.rpartition("/")
    folder = folder.replace("/", "\\")
    lines = [
        f"Mã nguồn: {asset.source_url}",
        f"Đóng nguyên dạng {len(comp.files)} file dữ liệu (không sửa nội dung, kể cả {license_name})"
        f" trong _internal\\{folder}\\.",
    ]
    if asset.license == "OFL-1.1":
        lines.append(
            "Font là tác phẩm riêng đi cùng chương trình (tác phẩm gộp): OFL-1.1 áp dụng cho file font,"
            " không cho Teleport."
        )
    text = Path(comp.license_path).read_text(encoding="utf-8")
    lines += [_SEPARATOR, f"[{comp.name}] {license_name}", "", text.rstrip()]
    return lines


def build_notices(
    components: dict[str, Component],
    python_files: dict[str, list[str]],
    sboms: dict[str, list[tuple[str, str, str, str]]],
    *,
    app_version: str,
    base_prefix: str | None = None,
    edition: Edition = CLI_EDITION,
    qt_files: list[tuple[QtEmbedded, list[str]]] | None = None,
) -> str:
    """Nội dung THIRD-PARTY-NOTICES.txt. Thiếu văn bản giấy phép nào thì `LicenseAuditError`.

    `qt_files` là kết quả của `qt_embedded_files` (thành phần lồng trong Qt và file chứa nó).
    """
    qt_files = qt_files or []
    python_license = ""
    extra_texts: list[tuple[str, str, str]] = []
    if "python" in components:
        python_license = _python_license_file(base_prefix).read_text(encoding="utf-8", errors="replace")
        extra_texts = _cpython_license_texts()
    all_python_text = "\n".join([python_license, *(text for _title, _source, text in extra_texts)])
    embedded = [entry for entry in PYTHON_EMBEDDED if entry[0] in python_files]
    for prefix, name, _lic, _where, markers in embedded:
        missing = [m for m in markers if not re.search(m, all_python_text)]
        if missing:
            raise LicenseAuditError(
                f"văn bản giấy phép của Python thiếu phần cho {name} "
                f"({', '.join(python_files[prefix])}): {missing}"
            )
    sbom_texts = {key: sbom_notice_texts(key, entries) for key, entries in sboms.items()}
    versions = _python_library_versions()
    lines = [
        f"Teleport {app_version} ({edition.label} cho Windows) - "
        "thông báo giấy phép của thành phần bên thứ ba",
        "",
        "Teleport phát hành theo GPL-3.0-or-later (file LICENSE cùng thư mục). Bản build này đóng gói",
        "kèm các thành phần dưới đây; mỗi thành phần giữ giấy phép riêng, văn bản đầy đủ ở phần sau.",
        "Mã nguồn đúng bản build: xem SOURCE.txt.",
        "",
        "Danh sách thành phần (tên, phiên bản, giấy phép theo metadata):",
    ]
    others = [c for k, c in sorted(components.items()) if k != "zero-cloud-lan-teleport"]
    for comp in others:
        lines.append(f"  - {comp.name} {comp.version}: {comp.license}")
    if embedded:
        lines.append("  - Thành phần bên thứ ba nằm trong các file của Python được đóng vào:")
        for prefix, name, lic, where, _markers in embedded:
            version = f" [{versions[prefix]}]" if prefix in versions else ""
            lines.append(f"      {name}{version} ({', '.join(python_files[prefix])}): {lic}.")
            lines.append(f"        Văn bản: {where}.")
    for key, entries in sorted(sboms.items()):
        lines.append(
            f"  - Thành phần liên kết tĩnh trong {components[key].name} theo SBOM của gói"
            " (SBOM liệt kê cả crate chỉ dùng lúc biên dịch):"
        )
        lines.extend(f"      {name} {version}: {expression}" for name, version, expression, _ in entries)
        own, uses_owner_text = sbom_texts[key]
        if uses_owner_text:
            lines.append(
                "      Thành phần có giấy phép thỏa được bằng Apache-2.0 dùng theo nhánh đó (văn bản"
                f" Apache-2.0 ở phần {components[key].name})."
            )
        if own:
            names = ", ".join(f"{name} {version}" for name, version, _expr, _texts in own)
            lines.append(
                f"      Văn bản giấy phép và dòng bản quyền riêng ở phần {components[key].name}: {names}."
            )
    if qt_files:
        lines.append(
            f"  - Thành phần bên thứ ba nằm trong Qt {QT_LICENSE_VERSION} (theo qt_attribution.json của"
            " qtbase và pyside-setup, REUSE.toml của qtsvg), văn bản ở cuối file này:"
        )
        for (_pattern, name, lic, _texts, _credit), files in qt_files:
            lines.append(f"      {name} ({', '.join(files)}): {lic}.")
    if "vcruntime140" in python_files:
        lines += ["", VCRUNTIME_NOTE]
    if any(comp.key in MSVC_RUNTIME_OWNERS for comp in others):
        lines += ["", MSVC_RUNTIME_NOTE]
    for comp in others:
        lines += ["", _SEPARATOR, f"{comp.name} {comp.version}", f"Giấy phép: {comp.license}"]
        if comp.key == "python":
            lines.append(
                f"Văn bản: LICENSE.txt của Python {comp.version}, rồi phần mềm tích hợp trong CPython"
                " (license.rst đúng phiên bản) và thư viện C của bản Windows mà LICENSE.txt chưa có"
            )
            lines += [_SEPARATOR, f"[Python] LICENSE.txt (từ thư mục cài Python {comp.version})", ""]
            lines.append(python_license.rstrip())
            for title, source, text in extra_texts:
                lines += [_SEPARATOR, f"[Python] {title}", f"Nguồn: {source}", "", text.rstrip()]
            continue
        if comp.asset is not None:
            lines += _asset_notice(comp)
            continue
        dist = md.distribution(comp.name)
        urls = _project_urls(dist)
        if comp.key in PACKAGE_SOURCE_URLS:
            urls = [PACKAGE_SOURCE_URLS[comp.key], *urls[1:]]  # bỏ link PyPI (không có sdist)
        lines.append("Mã nguồn: " + " ; ".join(urls))
        for name, version, expression, source in sboms.get(comp.key, []):
            if "theo http" in source:
                lines.append(f"Ghi chú: {name} {version} liên kết tĩnh, giấy phép {expression} ({source}).")
        override = PACKAGE_LICENSE_TEXTS.get(comp.key)
        if override is not None:
            if comp.key in sbom_texts:
                raise LicenseAuditError(
                    f"{comp.name}: có SBOM nhưng văn bản giấy phép lấy từ PACKAGE_LICENSE_TEXTS"
                )
            note, texts = override
            lines.append(note)
            for name, title, source in texts:
                text = (LICENSES_DIR / name).read_text(encoding="utf-8")
                lines += [_SEPARATOR, f"[{comp.name}] {title}", f"Nguồn: {source}", "", text.rstrip()]
            continue
        license_files = _license_files(dist)
        if not license_files:
            raise LicenseAuditError(f"{comp.name}: không có file giấy phép trong dist-info")
        license_texts = [(path, path.read_text(encoding="utf-8")) for path in license_files]
        for path, text in license_texts:
            lines += [_SEPARATOR, f"[{comp.name}] {path.name}", "", text.rstrip()]
        own, uses_owner_text = sbom_texts.get(comp.key, ([], False))
        if uses_owner_text and not any(_APACHE_TEXT.search(text) for _lic, text in license_texts):
            raise LicenseAuditError(
                f"{comp.name}: SBOM có thành phần dùng theo Apache-2.0 nhưng dist-info không có văn bản"
                " Apache-2.0"
            )
        for name, version, expression, notice_texts in own:
            for file_name, source in notice_texts:
                text = (LICENSES_DIR / file_name).read_text(encoding="utf-8")
                lines += [
                    _SEPARATOR,
                    f"[{comp.name}] {name} {version}: {expression}, thành phần trong SBOM của gói",
                    f"Nguồn: {source}",
                    "",
                    text.rstrip(),
                ]
    if qt_files:
        lines += [
            "",
            _SEPARATOR,
            f"Thành phần bên thứ ba lồng trong Qt {QT_LICENSE_VERSION} và PySide6/shiboken6",
            "Theo qt_attribution.json của qtbase và pyside-setup, REUSE.toml của qtsvg, đúng phiên bản.",
            "Thành phần có hai giấy phép (OR) được dùng theo nhánh tương thích GPLv3 (ví dụ FreeType",
            "theo FTL).",
        ]
        credits = sorted({credit for (_p, _n, _l, _t, credit), _files in qt_files if credit})
        lines += [f"Ghi công: {credit}" for credit in credits]
        printed: set[str] = set()
        for (_pattern, name, lic, texts_qt, _credit), files in qt_files:
            lines += ["", f"{name} (trong {', '.join(files)}): {lic}"]
            for file_name, source in texts_qt:
                if file_name in printed:
                    lines.append(f"  Văn bản: {file_name} (đã in ở trên)")
                    continue
                printed.add(file_name)
                text = (LICENSES_DIR / QT_LICENSES_DIR / file_name).read_text(encoding="utf-8")
                lines += [_SEPARATOR, f"[Qt {QT_LICENSE_VERSION}] {file_name}", f"Nguồn: {source}", ""]
                lines.append(text.rstrip())
    return "\n".join(lines) + "\n"


def build_source(
    components: dict[str, Component],
    *,
    repo_dir: Path,
    app_version: str,
    edition: Edition = CLI_EDITION,
) -> str:
    """Nội dung SOURCE.txt (URL repo, SHA commit, cách thay thư viện LGPL, nơi lấy mã nguồn)."""
    pyproject = tomllib.loads((repo_dir / "pyproject.toml").read_text(encoding="utf-8"))
    repo_url = pyproject["project"]["urls"]["Repository"].rstrip("/")
    sha = os.environ.get("GITHUB_SHA") or _git(repo_dir, "rev-parse", "HEAD")
    dirty = bool(_git(repo_dir, "status", "--porcelain"))
    tag = release_tag()
    lines = [
        f"Teleport {app_version} ({edition.label} cho Windows) - mã nguồn",
        "",
        "Teleport là phần mềm tự do theo GPL-3.0-or-later (file LICENSE).",
        f"Kho mã nguồn: {repo_url}",
        f"Commit dùng để build: {sha}",
        f"Mã nguồn đúng bản build: {repo_url}/tree/{sha}",
    ]
    if tag is not None:
        lines.append(f"Bản phát hành: {tag} ({repo_url}/releases/tag/{tag})")
    if dirty:
        lines.append(
            "CẢNH BÁO: bản build này dựng từ cây làm việc có thay đổi chưa commit, "
            "nên mã nguồn không trùng hoàn toàn commit trên. Đừng phát hành bản build này."
        )
    zeroconf = components.get("zeroconf")
    if zeroconf is not None:
        lines += [
            "",
            f"Thư viện LGPL: zeroconf {zeroconf.version} ({zeroconf.license}) nằm ở _internal\\zeroconf\\",
            f"dưới dạng file riêng (.py và .pyd), không gộp vào {edition.exe_name}. Bạn có thể thay cả thư",
            "mục đó bằng bản zeroconf đã sửa đổi có cùng API để chạy với Teleport. Các module .pyd (Cython)",
            "phụ thuộc lẫn nhau nên thay cả bộ: hoặc .pyd build cho đúng phiên bản Python ghi ở cuối file",
            "này, hoặc xóa mọi .pyd và đặt file .py tương ứng (zeroconf chạy được ở dạng Python thuần).",
        ]
        if tag is not None:
            pinned = LGPL_SDISTS.get("zeroconf")
            if pinned is None or pinned[0] != zeroconf.version:
                raise LicenseAuditError(
                    f"zeroconf {zeroconf.version} đóng vào khác bản sdist ghim trong LGPL_SDISTS"
                    f" ({pinned!r}); sửa LGPL_SDISTS cùng constraints.txt"
                )
            sdist = sdist_filename("zeroconf", zeroconf.version)
            lines += [
                f"Mã nguồn zeroconf {zeroconf.version} đúng bản đóng vào (sdist từ PyPI, SHA-256",
                f"{pinned[1]}) được đính kèm cùng trang phát hành:",
                f"{repo_url}/releases/download/{tag}/{sdist}",
                "Nơi khác có cùng mã nguồn: " + " ; ".join(_project_urls(md.distribution("zeroconf"))),
            ]
        else:
            lines.append("Mã nguồn zeroconf: " + " ; ".join(_project_urls(md.distribution("zeroconf"))))
    qt = components.get(QT_OWNER)
    if qt is not None:
        shiboken = components.get("shiboken6")
        shiboken_text = f", shiboken6 {shiboken.version}" if shiboken is not None else ""
        lines += [
            "",
            f"Thư viện LGPL: Qt {QT_LICENSE_VERSION} và PySide6 {qt.version}{shiboken_text} (dùng theo",
            "LGPL-3.0-only) nằm ở _internal\\PySide6\\ và _internal\\shiboken6\\ dưới dạng file riêng (DLL",
            f"Qt6*.dll, plugin của Qt, module .pyd của PySide6), không gộp vào {edition.exe_name}. Mã Qt và",
            "PySide6 không bị sửa. Bạn có thể thay các file đó bằng bản Qt/PySide6 đã sửa đổi, build từ mã",
            "nguồn dưới đây với cùng phiên bản và cùng trình biên dịch (MSVC, 64-bit) để giữ tương thích nhị",
            "phân; thay DLL Qt thì thay cả bộ Qt6*.dll và plugin cùng lúc.",
            f"Mã nguồn Qt {QT_LICENSE_VERSION}: {QT_SOURCE_URL}",
        ]
        if any(f.replace("\\", "/").lower() == "pyside6/qt6svg.dll" for f in qt.files):
            lines.append(f"Mã nguồn Qt SVG {QT_LICENSE_VERSION} (Qt6Svg.dll): {QTSVG_SOURCE_URL}")
        lines += [
            f"Mã nguồn PySide6/shiboken6 {QT_LICENSE_VERSION}: {PYSIDE_SOURCE_URL}",
            "Kho mã PySide6: " + " ; ".join(_project_urls(md.distribution(qt.name))[1:]),
        ]
    assets = [(comp, comp.asset) for _key, comp in sorted(components.items()) if comp.asset is not None]
    if assets:
        lines += ["", "Tài sản không phải mã, đóng nguyên dạng (file nguồn chính là file đã đóng vào):"]
        lines += [f"  {c.name} ({a.version}, {c.license}): {a.source_url}" for c, a in assets]
    lines += [
        "",
        "Mã nguồn các thành phần khác: xem dòng 'Mã nguồn:' của từng thành phần",
        "trong THIRD-PARTY-NOTICES.txt.",
        "",
        f"Công cụ build: Python {sys.version.split()[0]}, PyInstaller {md.version('pyinstaller')}, "
        f"pyinstaller-hooks-contrib {md.version('pyinstaller-hooks-contrib')}.",
    ]
    return "\n".join(lines) + "\n"


@dataclass
class AuditResult:
    """Kết quả kiểm giấy phép (trước EXE/COLLECT): thành phần và nội dung các file sẽ ghi sau COLLECT."""

    components: dict[str, Component]
    python_files: dict[str, list[str]]
    sboms: dict[str, list[tuple[str, str, str, str]]]
    notices: str  # nội dung THIRD-PARTY-NOTICES.txt
    source: str  # nội dung SOURCE.txt


def check(
    toc: Iterable[tuple[str, str, str]],
    *,
    repo_dir: Path,
    app_version: str,
    base_prefix: str | None = None,
    edition: Edition = CLI_EDITION,
) -> AuditResult:
    """Kiểm giấy phép mọi file trong TOC và dựng sẵn nội dung file giấy phép. Gọi trước EXE/COLLECT.

    Mọi phép kiểm (gói lạ, giấy phép chưa duyệt, SBOM, file Python lạ, LICENSE.txt của Python, văn
    bản CPython đúng phiên bản, thành phần lồng trong Qt, đoạn chữ bắt buộc, file giấy phép trong
    dist-info, SHA commit) đều chạy ở đây; lỗi thì `LicenseAuditError` (hoặc lỗi của git) trước khi
    có exe. `base_prefix` mặc định là `sys.base_prefix`.
    """
    components, python_files = collect_components(
        toc, repo_dir=repo_dir, base_prefix=base_prefix, edition=edition
    )
    sboms = audit(components, python_files)
    qt_files = qt_embedded_files(components)
    notices = build_notices(
        components,
        python_files,
        sboms,
        app_version=app_version,
        base_prefix=base_prefix,
        edition=edition,
        qt_files=qt_files,
    )
    source = build_source(components, repo_dir=repo_dir, app_version=app_version, edition=edition)
    report = ["Thành phần đóng vào bản build (giấy phép theo metadata; tài sản theo SOURCE_ASSETS):"]
    for _key, comp in sorted(components.items()):
        report.append(f"  {comp.name} {comp.version}: {comp.license} ({len(comp.files)} file)")
    for prefix, name, lic, _where, _markers in PYTHON_EMBEDDED:
        if prefix in python_files:
            report.append(f"  {name} ({', '.join(python_files[prefix])}, trong Python): {lic}")
    for key, entries in sorted(sboms.items()):
        report.append(f"  SBOM {components[key].name}: {len(entries)} thành phần, đều tương thích GPLv3")
    for (_pattern, name, lic, _texts, _credit), files in qt_files:
        report.append(f"  {name} (trong {', '.join(files)}, Qt): {lic}")
    log("\n".join(report))
    return AuditResult(components, python_files, sboms, notices, source)


def write_outputs(result: AuditResult, *, dist_dir: Path, repo_dir: Path) -> None:
    """Chỉ ghi file: LICENSE, THIRD-PARTY-NOTICES.txt, SOURCE.txt vào `dist_dir`. Gọi sau COLLECT."""
    (dist_dir / "LICENSE").write_bytes((repo_dir / "LICENSE").read_bytes())
    (dist_dir / "THIRD-PARTY-NOTICES.txt").write_text(result.notices, encoding="utf-8")
    (dist_dir / "SOURCE.txt").write_text(result.source, encoding="utf-8")


# Tên thư mục onedir trong distpath (COLLECT name trong teleport-cli.spec và teleport-gui.spec). Hai tên
# phải khác nhau kể cả khi không phân biệt hoa thường (Windows), nên bản GUI không lấy tên "Teleport".
DIST_NAME = "teleport"
GUI_DIST_NAME = "teleport-gui"
DIST_NAMES: frozenset[str] = frozenset({DIST_NAME, GUI_DIST_NAME})


def remove_stale_dist(distpath: Path, name: str) -> bool:
    """Xóa bản build cũ `distpath/<name>` khi `check` hỏng; trả True nếu đã xóa.

    `--clean` của PyInstaller không dọn distpath (chỉ COLLECT mới thay thư mục), nên nếu không xóa thì
    dist/ vẫn còn exe của lần build trước dù lần này kiểm giấy phép hỏng. Chỉ xóa đúng thư mục có tên
    trong `DIST_NAMES` (so đúng chữ) nằm thẳng trong `distpath`: tên khác, link/junction, hay không
    phải thư mục thì `ValueError` và không xóa gì.
    """
    if name not in DIST_NAMES:
        raise ValueError(f"chỉ xóa thư mục {sorted(DIST_NAMES)!r} trong distpath, không xóa {name!r}")
    root = Path(os.path.abspath(distpath))
    target = root / name
    if not os.path.lexists(target):
        return False
    if target.is_symlink() or os.path.isjunction(target) or not target.is_dir():
        raise ValueError(f"không xóa {target}: không phải thư mục thường")
    if target.resolve().parent != root.resolve():
        raise ValueError(f"không xóa {target}: không nằm thẳng trong {root}")
    shutil.rmtree(target)
    return True


def log(text: str) -> None:
    """In ra log build; console Windows có thể không phải UTF-8 nên thay ký tự không in được."""
    encoding = sys.stdout.encoding or "utf-8"
    print(text.encode(encoding, "backslashreplace").decode(encoding), flush=True)
