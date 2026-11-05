# Quy trình phát triển

## Nhánh
- `main` luôn chạy được và được bảo vệ: chỉ merge qua Pull Request khi CI xanh.
- Mỗi việc làm trên một nhánh riêng: `feat/<tên>`, `fix/<tên>`, `docs/<tên>`…

## Commit
Theo [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: thêm khám phá thiết bị qua mDNS
fix: chặn tên file chứa ../ khi nhận
docs: cập nhật hướng dẫn tường lửa
test: thêm test nối lại khi rớt mạng
```

Thay đổi nào người dùng nhận thấy được thì ghi thêm vào mục `[Unreleased]` của [CHANGELOG.md](CHANGELOG.md), chia `### Added` / `### Changed` / `### Fixed` / `### Security`, mỗi dòng viết cho người dùng hiểu. Mục `[Unreleased]` chưa phát hành, nên dòng cũ nói ngược hành vi mới thì sửa dòng cũ, không thêm dòng mâu thuẫn. Thay đổi giao thức: mục “Thay đổi giao thức” bên dưới.

## Cài môi trường

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev,gui]"
```

Extra `gui` cài PySide6 cho giao diện (`teleport-gui`) và test `tests/ui/`; `dev` cũng tự kéo nó theo vì `pytest-qt` cần. Trên Linux, Qt còn cần vài thư viện hệ thống, kể cả khi test chạy không màn hình (`QT_QPA_PLATFORM=offscreen`, [architecture.md](architecture.md) mục 6); danh sách gói là bước Linux trong [.github/workflows/ci.yml](../.github/workflows/ci.yml) (Ubuntu: `sudo apt-get install` các gói đó).

## Trước khi mở Pull Request

```powershell
ruff check .
ruff format .
mypy src
pytest
```

Muốn nhanh hơn thì chạy `pytest -n 4 --dist loadgroup -m "not gui"` và `pytest -n 4 --dist loadgroup -m gui` (song song, test giao diện là một lần chạy riêng; hai lệnh chạy cùng lúc ở hai terminal được; vì sao không dùng `-n auto` trên máy nhiều lõi: [architecture.md](architecture.md) mục 6).

CI ([.github/workflows/ci.yml](../.github/workflows/ci.yml)) chạy `ruff check .`, `ruff format --check .`, `mypy src`, `pytest -n auto --dist loadgroup -m "not gui"` trên Windows, macOS, Linux × Python 3.12 và 3.14; test giao diện chạy ở job riêng song song với job đó (`pytest -n auto --dist loadgroup -m gui`; riêng Windows chạy tuần tự `pytest -m gui`, chia ba job theo `TELEPORT_SHARD`). Push commit mới vào một PR thì lần chạy CI cũ của PR đó bị hủy. Vì vậy hãy chạy `ruff format .` trước khi push, để bước kiểm tra định dạng không báo lỗi.

PR đổi giao diện: đính kèm ảnh sáng/tối do `tests/ui/test_snapshots.py` sinh (lệnh: [architecture.md](architecture.md) mục 6), không commit ảnh vào repo.

Mức kiểm tra kiểu của từng gói nằm ở `[tool.mypy]` trong `pyproject.toml`. Lỗi kiểu thì sửa chú thích; chỉ dùng `# type: ignore[<mã lỗi>]` kèm lý do khi không còn cách nào khác.

Mạng hoặc máy CI chặn multicast thì đặt biến môi trường `TELEPORT_SKIP_MDNS=1` để bỏ qua các test mDNS thật (marker `mdns`).

## Bản dịch
Chuỗi nguồn của giao diện là tiếng Việt; bản English nằm ở `src/teleport/ui/i18n/teleport_en.ts` (để review) và `teleport_en.qm` (file app nạp, sinh từ `.ts`). Chạy từ gốc repo:

```powershell
python packaging/i18n/update.py            # trích chuỗi từ src/teleport/ui, gộp vào .ts, rồi sinh .qm
python packaging/i18n/update.py --check    # không ghi gì; thoát 1 nếu .ts lỗi thời hoặc còn câu chưa dịch
```

Luật:
- PR thêm hoặc sửa chữ của giao diện cập nhật `.ts` và `.qm` trong cùng PR, với bản dịch đầy đủ. Thiếu thì `tests/ui/test_translations.py` đỏ trên CI (có chủ ý).
- Mọi chuỗi đi qua `QCoreApplication.translate("NgữCảnh", "chuỗi literal")` (được dùng bí danh như `t = QCoreApplication.translate`). Không dùng `self.tr(...)` và không truyền biến làm chuỗi nguồn: bộ trích đọc mã bằng `ast` và báo lỗi những chỗ đó.
- Câu có số đếm dùng `%n` và tham số `n` (`translate(ctx, "%n máy", None, n)`), không dùng `{n}`; giá trị khác chèn bằng `texts.fill` với `{tên}`, và bản dịch giữ nguyên mọi `{tên}`.
- Thông báo còn hiện lâu theo trạng thái (dải thông báo, lỗi đọc cài đặt) nhận `texts.Text`: truyền hàm dựng câu thay vì chuỗi đã dịch, để đổi ngôn ngữ thì câu được dịch lại.
- Không dịch tên tự gọi của ngôn ngữ (“Tiếng Việt”), `APP_NAME`, log, CLI và argparse.

Văn phong English: sentence case, thuật ngữ Windows, “…” ở nút mở hộp thoại. Bảng thuật ngữ (nguồn duy nhất):

| Tiếng Việt | English |
|---|---|
| máy | device |
| ghép đôi / hủy ghép đôi | pair / unpair |
| thiết bị tin cậy | trusted devices |
| lượt truyền | transfer |
| thư mục nhận | receive folder |
| đang ẩn / đang hiện | hidden / visible |
| Tìm máy mới | Find devices |
| mã ghép đôi | pairing code |
| khay hệ thống | system tray |
| nhận dở | partially received |
| Thoát | Exit |
| Thử lại | Try again |
| Trùng khớp / Không trùng | Match / Don't match |
| Nhận / Từ chối (hộp nhận file) | Accept / Decline |
| mã máy | device ID |
| danh tính | identity |
| thư mục cấu hình | configuration folder |
| cửa sổ dòng lệnh | command prompt window |
| Bấm … | Click … |

## Build thử bản CLI (Windows)
Bản CLI được đóng gói bằng PyInstaller. Build thử theo mục này không gắn tag, không tạo GitHub Release; bản phát hành build bằng đúng các bước này qua workflow phát hành (mục “Phát hành”). File build nằm trong `packaging/pyinstaller/`: `teleport-cli.spec` (cấu hình build), `third_party.py` (kiểm giấy phép, sinh file giấy phép), `requirements.txt` (công cụ build, ghim phiên bản) và `constraints.txt` (ghim bản dependency runtime được đóng vào exe).

Chạy từ gốc repo, trên cây làm việc đã commit hết:

```powershell
pip install -e ".[dev]" -r packaging/pyinstaller/requirements.txt -c packaging/pyinstaller/constraints.txt
$env:PYTHONUTF8 = "1"   # như workflow
pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/pyinstaller/teleport-cli.spec
```

Bản build theo chế độ `--onedir`, không `--onefile` (lý do: [ke_hoach.md](ke_hoach.md) mục 5.2, Giai đoạn 6). Kết quả nằm trong `dist/teleport/`: `teleport.exe`, thư viện trong `_internal/`, cùng `LICENSE`, `THIRD-PARTY-NOTICES.txt` (giấy phép các thành phần đóng vào) và `SOURCE.txt` (commit dùng để build, nơi lấy mã nguồn). Build từ cây làm việc còn thay đổi chưa commit thì `SOURCE.txt` ghi cảnh báo, và bản build đó không được phát hành. `build/` và `dist/` đã có trong `.gitignore`.

`third_party.py` kiểm giấy phép mọi gói thật sự đóng vào và **làm build thất bại** (`LicenseAuditError`) khi gặp gói hay giấy phép chưa duyệt, file không rõ thuộc gói nào, hoặc thành phần trong SBOM của gói có giấy phép chưa duyệt. Khi đó đừng lách: đối chiếu luật giấy phép ở [ke_hoach.md](ke_hoach.md) mục 1 (Giấy phép) và mục 4.1, hợp lệ thì mới sửa `APPROVED` trong `third_party.py` (cách làm: docstring của file). Riêng Universal CRT mà PyInstaller tìm thấy trên `PATH` (ví dụ trong thư mục `bin` của JDK) bị spec bỏ khỏi bản build trước bước kiểm, log build ghi số file đã bỏ (lý do: [ke_hoach.md](ke_hoach.md) mục 1, Giấy phép).

Chạy test khói trên exe vừa build (marker `frozen`, [architecture.md](architecture.md) mục 6). Nâng bản công cụ build trong `requirements.txt` hay dependency runtime trong `constraints.txt` thì build lại rồi chạy lại bước này; nâng mà đổi giấy phép thì duyệt lại theo [ke_hoach.md](ke_hoach.md) mục 1 rồi sửa `APPROVED`.

```powershell
$env:TELEPORT_FROZEN_EXE = "$PWD\dist\teleport\teleport.exe"
pytest -m frozen
```

Build trên GitHub: workflow `build-cli` ([.github/workflows/build-cli.yml](../.github/workflows/build-cli.yml)) chạy tay (`workflow_dispatch`), hoặc được workflow phát hành gọi lại (`workflow_call`, mục “Phát hành”). Vào tab Actions → “Build CLI (thử)” → Run workflow, chọn nhánh `main` hoặc tag `vX.Y.Z` (hoặc `gh workflow run build-cli.yml --ref main`, `--ref vX.Y.Z`); nút chạy tay chỉ hiện khi file workflow đã có trên nhánh mặc định. Workflow build bằng đúng lệnh trên, chạy `pytest -m frozen` trên exe, rồi tải lên artifact `teleport-cli-<phiên bản>-<sha7>-windows`. Artifact là bản tạm, tự xóa sau thời hạn `retention-days` của workflow. File zip tải về chứa thẳng `teleport.exe`, `_internal\` và ba file giấy phép, không có thư mục bọc ngoài, nên hãy giải nén vào một thư mục riêng (ví dụ `C:\tp\teleport\`).

## Build thử bản GUI (Windows)
Bản GUI (`Teleport.exe`, cửa sổ, không mở cửa sổ dòng lệnh) đóng gói như bản CLI ở mục trên, cùng `third_party.py`, `requirements.txt` và `constraints.txt`, nhưng dùng spec `teleport-gui.spec` và điểm vào `launcher_gui.py` (gọi `teleport.ui.app:main`). Đây là bản zip giải nén là chạy, chưa phải bộ cài; build thử không gắn tag, không tạo GitHub Release. Môi trường build cần extra `gui` (đã nằm trong `.[dev]`).

```powershell
pip install -e ".[dev]" -r packaging/pyinstaller/requirements.txt -c packaging/pyinstaller/constraints.txt
$env:PYTHONUTF8 = "1"
pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/pyinstaller/teleport-gui.spec
```

Kết quả nằm trong `dist/teleport-gui/` (tên thư mục khác `dist/teleport/` của bản CLI vì Windows không phân biệt hoa thường): `Teleport.exe`, `_internal/`, ba file giấy phép như bản CLI và `DOC-TRUOC.txt`, hướng dẫn cho người chạy bản zip (giải nén, SmartScreen, tường lửa, hồ sơ mạng Private, thư mục nhận, log). `DOC-TRUOC.txt` là nguồn duy nhất của các hướng dẫn đó cho người dùng cuối; nguồn của nó là `packaging/pyinstaller/DOC-TRUOC.txt`, spec ghi ra UTF-8 có BOM, xuống dòng CRLF. Icon của `Teleport.exe` là `packaging/pyinstaller/teleport.ico`, sinh từ logo SVG trong `ui/logo.py` bằng `make_icon.py` cùng thư mục: sửa logo trong `ui/logo.py` hoặc nâng PySide6 thì chạy lại script đó (`--check` báo file đã cũ) rồi commit file mới. Qt/PySide6 dùng theo LGPL-3.0 nên phải là `--onedir`: DLL Qt nằm riêng trong `_internal\PySide6\`, người dùng thay được; `SOURCE.txt` ghi cách thay và nơi lấy mã nguồn Qt, PySide6. Spec chỉ đóng phần Qt mà `ui` dùng (gồm `Qt6Svg.dll` để vẽ icon SVG); danh sách phần bị bỏ (QtQml, QtQuick, QtPdf, QtSvgWidgets, `opengl32sw.dll`, bản dịch và plugin không dùng, kể cả `imageformats`, `iconengines`) là `QT_UNUSED` trong spec, log build ghi số file đã bỏ. Spec đóng mọi file trong `src/teleport/ui/assets/` (icon, font và file giấy phép của chúng) nguyên dạng; `third_party.py` xếp chúng vào thành phần tài sản theo `SOURCE_ASSETS` (nguồn, commit ghim, giấy phép) và dừng build khi trong `assets/` có file không thuộc mục nào. Thêm hay thay icon, font thì lấy từ đúng nguồn ở commit ghim, sửa `SOURCE_ASSETS` và mục 4.1 của [ke_hoach.md](ke_hoach.md).

`third_party.py` kiểm thêm thành phần lồng bên trong DLL Qt (`QT_EMBEDDED`, rà theo `qt_attribution.json` của đúng phiên bản Qt, riêng qtsvg theo `REUSE.toml`, văn bản giấy phép chép sẵn trong `packaging/pyinstaller/licenses/qt-<phiên bản>/`). Build dừng khi phiên bản PySide6 khác phiên bản đã rà, hoặc khi có DLL/plugin Qt chưa rà (`QT_REVIEWED_FILES`), ví dụ sau khi `ui` dùng thêm một module Qt. Khi đó rà lại `qt_attribution.json` của qtbase và pyside-setup đúng tag mới rồi mới sửa các bảng đó (cách làm: docstring của `third_party.py`). Build (cả bản CLI) cũng dừng khi giấy phép trong metadata của bản `zero-cloud-lan-teleport` đã cài khác `APPROVED`: sau khi kéo thay đổi `license` của `pyproject.toml` về, chạy lại `pip install -e .` trong môi trường build để metadata được cập nhật.

Test khói (marker `frozen`) của bản GUI dùng biến riêng, để chạy được cùng lúc với test của bản CLI; exe không có stdout nên test chỉ kiểm mã thoát của `--selftest` và bố cục thư mục:

```powershell
$env:TELEPORT_FROZEN_GUI_EXE = "$PWD\dist\teleport-gui\Teleport.exe"
pytest -m frozen
```

Build trên GitHub: workflow `build-gui` ([.github/workflows/build-gui.yml](../.github/workflows/build-gui.yml)), chạy tay hoặc được workflow phát hành gọi lại như `build-cli` (“Build GUI (thử)”, hoặc `gh workflow run build-gui.yml --ref main`). Artifact `teleport-gui-<phiên bản>-<sha7>-windows` riêng với zip CLI và, khác zip CLI, có thư mục bọc: giải nén ra `teleport-gui\` chứa `Teleport.exe`, `_internal\`, ba file giấy phép và `DOC-TRUOC.txt`. Chạy thử bản zip (tường lửa, SmartScreen, chỗ giải nén): làm theo `DOC-TRUOC.txt`.

## Bộ cài Windows (Inno Setup)
Bộ cài đóng thư mục `dist/teleport-gui/` của mục trên bằng Inno Setup, theo script `packaging/inno/teleport.iss` (bản dịch tiếng Việt của Inno trong `packaging/inno/languages/`, giấy phép Inno trong `packaging/inno/licenses/`). Bộ cài chưa ký mã. Build thử không gắn tag, không tạo GitHub Release; bộ cài phát hành do workflow phát hành build bằng cùng các bước (mục “Phát hành”). Bộ cài cài gì, tạo rule tường lửa nào, gỡ thì giữ/xóa gì: [architecture.md](architecture.md) mục 4 (“Bộ cài Windows”); giấy phép của Inno: [ke_hoach.md](ke_hoach.md) mục 1 (Giấy phép).

Dùng đúng bản Inno Setup mà workflow ghim (`INNO_VERSION`, `INNO_URL`, `INNO_SHA256` trong [.github/workflows/build-gui.yml](../.github/workflows/build-gui.yml)): tải bộ cài từ GitHub Release chính thức của `jrsoftware/issrc` ở `INNO_URL`, so SHA-256 với `INNO_SHA256` rồi mới cài. Bản khác thì giấy phép và `Vietnamese.isl` chưa được rà. Build từ gốc repo, sau khi đã build `dist/teleport-gui/`; ba tham số `/D` là bắt buộc, phiên bản lấy từ `teleport.__version__` (`AppVersionNumeric`: phần release của phiên bản, đệm 0 đủ 4 số, ví dụ `0.1.0a0` → `0.1.0.0`):

```powershell
$v = python -c "import teleport; print(teleport.__version__)"
$n = python -c "import teleport; from packaging.version import Version; r = list(Version(teleport.__version__).release); print('.'.join(map(str, r + [0] * (4 - len(r)))))"
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=$v /DAppVersionNumeric=$n "/DSourceDir=$PWD\dist\teleport-gui" "/O$PWD\installer" packaging\inno\teleport.iss
```

Kết quả là một file `installer\teleport-setup-<phiên bản>-x64.exe` (`installer/` đã có trong `.gitignore`). Cài thử không cần quyền quản trị, không tạo rule tường lửa, vào thư mục riêng (đường dẫn thư mục cài nên ngắn: thư mục quá sâu làm bộ cài lỗi 206, tên file quá dài):

```powershell
.\installer\teleport-setup-<phiên bản>-x64.exe /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER /DIR=C:\tp\cai-thu /LOG=C:\tp\cai.log
C:\tp\cai-thu\unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /LOG=C:\tp\go.log
```

Test cài/gỡ trên bộ cài (marker `frozen`, [architecture.md](architecture.md) mục 6) dùng biến riêng; chạy khi máy chưa cài Teleport bằng bộ cài, ca rule tường lửa chỉ chạy khi terminal có quyền quản trị:

```powershell
$env:TELEPORT_INSTALLER_EXE = "$PWD\installer\teleport-setup-<phiên bản>-x64.exe"
pytest tests/packaging/test_installer.py -m frozen
```

Workflow `build-gui` làm tiếp các bước này sau test khói của exe: cài Inno bản ghim, build bộ cài, dừng nếu bộ cài vượt cỡ ở mvp N11, ghi cỡ (MiB và byte) vào Step Summary, chạy test trên, rồi tải lên artifact `teleport-gui-setup-<phiên bản>-<sha7>-windows` chứa file bộ cài, riêng với zip `teleport-gui-…`.

Khắc phục sự cố: hai rule tường lửa của bản cài cho cả máy chỉ cho máy cùng subnet vào (`remoteip=localsubnet`); máy ở subnet khác hay đi qua VPN thì Windows chặn, kể cả khi gõ IP thủ công.

## Phát hành
1. Chuyển mục `[Unreleased]` trong `CHANGELOG.md` thành `[X.Y.Z] - YYYY-MM-DD`, đúng số của tag (bản thử nghiệm: `[0.1.0-alpha] - YYYY-MM-DD`). Workflow phát hành lấy nội dung Release từ đúng mục này.
2. Cập nhật `__version__` trong `src/teleport/__init__.py`. Đây là nguồn duy nhất của số phiên bản; `pyproject.toml` tự đọc từ đó.
3. Sửa các câu nói về hiện trạng nếu bản này làm chúng đổi: khung NOTE và bảng Lộ trình của `README.md`, mục “Phiên bản được hỗ trợ” của [SECURITY.md](SECURITY.md).
4. Sau khi merge vào `main`, chạy khô workflow phát hành trên `main` (bên dưới) và xem file trong artifact.
5. Gắn tag `vX.Y.Z` lên commit đó của `main` rồi push tag. Workflow phát hành tự build và tạo GitHub Release.

Đánh số theo [SemVer](https://semver.org/lang/vi/). Phiên bản giao thức mạng đánh số riêng, độc lập với phiên bản app.

Bản thử nghiệm (alpha, beta) ghi số ở hai dạng, và đây là nơi duy nhất ghi luật này:
- Tag và tiêu đề trong `CHANGELOG.md` theo SemVer: `v0.1.0-alpha`, `[0.1.0-alpha]`.
- `__version__` theo PEP 440, dạng mà công cụ đóng gói Python tự chuẩn hóa về: `0.1.0a0` (beta: `0.3.0b0`). `teleport --version`, tên artifact build thử và tên file phát hành hiện dạng này.
- Bản thường thì hai dạng bằng nhau (`v1.0.0` ↔ `1.0.0`). Dạng khác (rc, `a1`, `.dev`, `.post`) không phát hành được: workflow dừng.
- `__version__` có thể đã mang số của bản sắp gắn tag; bản build thử từ `main` khi chưa có tag cũng hiện số đó, phân biệt bằng `<sha7>`.

Bản thử nghiệm (alpha, beta) được phát hành thành GitHub Release đánh dấu pre-release; từ `v1.0.0` là Release thường. Hiện chỉ có bản Windows; bộ cài macOS, Linux và ký mã là việc của Giai đoạn 6 ([ke_hoach.md](ke_hoach.md) mục 5.2).

Workflow phát hành `release` ([.github/workflows/release.yml](../.github/workflows/release.yml), “Phát hành” trong tab Actions) chạy khi push tag `v*`. Các bước kiểm và chuẩn bị nằm trong `packaging/release/release.py` (cách gọi: docstring của file):
- `prepare`: dừng nếu tag không khớp `__version__` theo luật trên, nếu commit của tag không nằm trên `main`, hay nếu `CHANGELOG.md` không có mục của bản đó. Nội dung Release là mục đó cộng vài dòng cố định (bản chưa ký mã: SmartScreen “More info” → “Run anyway”; đọc `DOC-TRUOC.txt`; kiểm SHA-256). Tải sdist của thư viện LGPL (zeroconf) đúng bản ghim từ PyPI và kiểm SHA-256 (`LGPL_SDISTS` trong `packaging/pyinstaller/third_party.py`, phải bằng bản ghim trong `constraints.txt`).
- `cli`, `gui`: gọi lại `build-cli.yml` và `build-gui.yml`, nên bản phát hành qua đúng các bước và phép kiểm của build thử (bản Python ghim, Inno Setup ghim kèm SHA-256, `pytest -m frozen`, test cài/gỡ, chặn cỡ bộ cài theo mvp N11). Workflow đặt `TELEPORT_RELEASE_TAG` khi build để `SOURCE.txt` chỉ tới sdist zeroconf trên trang Release của tag (LGPL-2.1 §6: mã nguồn chép được từ cùng nơi phát bản nhị phân).
- `publish`, job duy nhất có quyền ghi (`contents: write`, chỉ dùng `GITHUB_TOKEN`): đóng `teleport-cli-<phiên bản>-windows-x64.zip` (thư mục bọc `teleport\`), `teleport-gui-<phiên bản>-windows-x64.zip` (thư mục bọc `teleport-gui\`), lấy `teleport-setup-<phiên bản>-x64.exe` và `zeroconf-<bản>.tar.gz`, ghi `SHA256SUMS.txt` cho các file đó, rồi tạo GitHub Release cho tag. Tên file không có `<sha7>` vì Release cố định theo tag. Release của tag đã có thì job dừng, không ghi đè.

Chạy khô: Actions → “Phát hành” → Run workflow trên `main` (ô `dry_run` bật sẵn), hoặc `gh workflow run release.yml --ref main`; nút chạy tay chỉ hiện khi file workflow đã có trên nhánh mặc định. Chạy khô build như bản phát hành (kể cả `SOURCE.txt` trỏ tới tag sắp gắn) và tải các file lên artifact `release-files-<phiên bản>`, nhưng không tạo Release; `CHANGELOG.md` chưa có mục của bản đó thì nội dung chỉ có một dòng ghi chú. Tắt `dry_run` chỉ được khi chạy trên một tag, dùng khi lần chạy theo push tag hỏng vì lỗi tạm thời.

## Thay đổi giao thức
Mọi thay đổi định dạng trên dây phải cập nhật [protocol.md](protocol.md) trong cùng Pull Request. Thay đổi không tương thích thì tăng số phiên bản giao thức ([protocol.md](protocol.md) mục 9).

## Giấy phép
Dự án theo giấy phép [GPL-3.0-or-later](../LICENSE). Gửi Pull Request nghĩa là bạn đồng ý đóng góp của mình được phát hành theo cùng giấy phép đó. Chỉ thêm thư viện có giấy phép tương thích GPLv3 (danh sách giấy phép được chấp nhận: [ke_hoach.md](ke_hoach.md) mục 1 (Giấy phép) và mục 4.1).

## Bảo mật
Báo lỗ hổng: xem [SECURITY.md](SECURITY.md).

Mọi dữ liệu nhận từ máy khác đều coi là không tin cậy: kiểm tra kiểu, độ dài và giá trị của từng trường trước khi dùng. Tên file nhận được phải được làm sạch trước khi ghi ra đĩa.
