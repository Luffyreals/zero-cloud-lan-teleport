"""Phần thuần (không widget) của việc gửi file từ giao diện: lấy đường dẫn, kiểm trước, câu lỗi.

- `local_paths(urls)`: đường dẫn của các URL file cục bộ (kéo thả, “Gửi file…”), giữ thứ tự, bỏ
  URL khác. Không chạm đĩa: thread Qt không `stat` file người dùng (spec-hackathon D7); file không
  có, thư mục, không đọc được… do `transfers.send` báo bằng `SourceError`. File `.lnk` gửi nguyên.
- `clipboard_paths(mime)`: đường dẫn của file đã chép (phím Dán trong luồng chat, `ui.shortcuts`),
  luật tất cả hoặc không: chỉ khi mọi URL là file cục bộ; có URL nào khác (https…) hay không có URL
  → `[]`. Chỉ đọc `urls()`, không đọc chữ hay ảnh, không chạm đĩa. Thả file vẫn theo `local_paths`
  (bỏ URL lạ).
- `selection_error(paths)`: lỗi nhận ra được mà không chạm đĩa (spec-hackathon mục 9.9): quá
  `MAX_OFFER_FILES` file, một file chọn hai lần (so `os.path.normcase(os.path.abspath(...))`, như
  `app.sources.prepare_sources`). Đếm trước, trùng sau.
- `send_error_message(error, peer)`: câu mvp mục 8 cho lỗi của `transfers.send` (dòng “Chọn
  gửi…”, khớp `cli.source_error_message`; tên lệnh trong “…”, không backtick).
- `not_paired_message(peer)`: câu mvp mục 8 “Chưa ghép đôi với *X* nên chưa gửi được…”.
- `blocked_message(result, peer)`: câu mvp mục 8 khi thiết bị đang bị chặn kết nối
  (`ConnectFailed` gần nhất, spec-hackathon mục 10 A2); không bị chặn → None.

Chuỗi qua `QCoreApplication.translate("Send", ...)` lúc gọi; chèn bằng `texts.fill` (một lượt).
`peer` là tên máy kia đã qua `texts.peer_label`; tên file qua `texts.file_label`; đường dẫn đầy đủ
trên máy này qua `printable` (ký tự điều khiển, surrogate lẻ, ký tự vô hình thành U+FFFD, như
`cli._printable`).
"""

from __future__ import annotations

import asyncio
import os
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QMimeData, QUrl

from teleport.app import sources as app_sources
from teleport.app.sources import SourceError, SourceErrorKind
from teleport.core.filenames import INVISIBLE_CHARS
from teleport.core.links import ConnectResult
from teleport.core.messages import MAX_OFFER_FILES
from teleport.ui import texts
from teleport.ui.texts import fill as _fill

_REPLACEMENT = "�"  # U+FFFD


def printable(text: str) -> str:
    """Ký tự Cc, Cs và ký tự vô hình / đổi hướng chữ (`INVISIBLE_CHARS`) thành U+FFFD."""
    return "".join(
        _REPLACEMENT if ch in INVISIBLE_CHARS or unicodedata.category(ch) in ("Cc", "Cs") else ch
        for ch in text
    )


def local_paths(urls: Iterable[QUrl]) -> list[Path]:
    """Đường dẫn của các URL file cục bộ, giữ thứ tự; URL không phải file cục bộ bị bỏ qua."""
    paths: list[Path] = []
    for url in urls:
        if not url.isLocalFile():
            continue
        local = url.toLocalFile()
        if local:
            paths.append(Path(local))
    return paths


def clipboard_paths(mime: QMimeData | None) -> list[Path]:
    """Đường dẫn của các file đã chép trong `mime` (clipboard), giữ thứ tự; không phải toàn URL file
    cục bộ → `[]`."""
    if mime is None or not mime.hasUrls():
        return []
    urls = mime.urls()
    paths = local_paths(urls)
    return paths if urls and len(paths) == len(urls) else []


def selection_error(paths: Sequence[Path]) -> str | None:
    """Câu lỗi khi danh sách chọn gửi sai mà không cần chạm đĩa; rỗng hay hợp lệ → None."""
    if not paths:
        return None
    t = QCoreApplication.translate
    limit = MAX_OFFER_FILES
    if len(paths) > limit:
        return t("Send", "Mỗi lần gửi được tối đa %n file.", None, limit)
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(os.path.abspath(os.fspath(path)))
        if key in seen:
            return _duplicate()
        seen.add(key)
    return None


def _duplicate() -> str:
    return QCoreApplication.translate("Send", "Có file được chọn hai lần. Hãy chọn mỗi file một lần.")


def source_error_message(error: SourceError) -> str:
    """Câu mvp mục 8 (các dòng “Chọn gửi…”) cho một `SourceError`."""
    t = QCoreApplication.translate
    path = error.path
    name = texts.file_label(path.name or str(path))
    kind = error.kind
    if kind is SourceErrorKind.NOT_A_FILE:
        return _fill(
            t("Send", "{name} không phải là file. Teleport chưa gửi được cả thư mục; hãy chọn từng file."),
            name=name,
        )
    if kind is SourceErrorKind.NOT_FOUND:
        return _fill(t("Send", "Không tìm thấy file {path}."), path=printable(str(path)))
    if kind is SourceErrorKind.PERMISSION:
        return _fill(t("Send", "Không mở được {name}: máy này không có quyền đọc file đó."), name=name)
    if kind is SourceErrorKind.TOO_LARGE:
        size = "?" if error.size is None else texts.format_size(error.size)
        limit = texts.format_size(app_sources.MAX_FILE_SIZE, trim=True)
        return _fill(
            t(
                "Send",
                "Không gửi được {name} ({size}): Teleport chỉ gửi được file tối đa {limit}. "
                "Hãy chia file thành nhiều phần nhỏ hơn rồi gửi.",
            ),
            name=name,
            size=size,
            limit=limit,
        )
    if kind is SourceErrorKind.BAD_NAME:
        return _fill(
            t(
                "Send",
                "Không gửi được {name}: tên file có ký tự không hiển thị được. Hãy đổi tên file rồi gửi lại.",
            ),
            name=name,
        )
    return _fill(t("Send", "Không đọc được {name}: ổ đĩa báo lỗi."), name=name)


def not_paired_message(peer: str) -> str:
    """mvp mục 8, “Giao diện: gửi tới thiết bị không (còn) ghép đôi”. `peer` đã qua `peer_label`."""
    return _fill(
        QCoreApplication.translate(
            "Send", "Chưa ghép đôi với {name} nên chưa gửi được. Hãy ghép đôi rồi gửi lại."
        ),
        name=peer,
    )


def send_error_message(error: BaseException, peer: str) -> str | None:
    """Câu báo lỗi của `transfers.send`; None khi không cần báo (node đang dừng).

    `peer`: tên máy nhận đã qua `texts.peer_label`. `SourceError` → câu theo `kind`; `KeyError`
    (chưa / không còn ghép đôi) → câu chưa ghép đôi; `RuntimeError` hay bị hủy → None; lỗi khác
    (kể cả `ValueError`: chọn trùng đã được `selection_error` lọc trước nên không đoán là trùng)
    → câu chung.
    """
    if isinstance(error, SourceError):
        return source_error_message(error)
    if isinstance(error, KeyError):
        return not_paired_message(peer)
    if isinstance(error, RuntimeError | asyncio.CancelledError):
        return None
    return _fill(
        QCoreApplication.translate("Send", "Không gửi được file tới {name}. Hãy thử lại."), name=peer
    )


def blocked_message(result: ConnectResult | str, peer: str) -> str | None:
    """Câu mvp mục 8 khi kết nối tới thiết bị đang bị chặn; không bị chặn → None.

    `result`: `ConnectResult` (hay giá trị chuỗi của nó) của `ConnectFailed` gần nhất. `peer`: tên
    máy kia đã qua `texts.peer_label`.
    """
    t = QCoreApplication.translate
    value = str(result)
    if value == ConnectResult.REJECTED.value:
        return _fill(
            t("Send", "{name} từ chối kết nối từ máy này. Có thể máy đó đã hủy ghép đôi."), name=peer
        )
    if value == ConnectResult.IDENTITY_MISMATCH.value:
        return _fill(
            t(
                "Send",
                "{name} đang dùng một danh tính khác với lúc ghép đôi. "
                "Có thể có người đang giả mạo máy này. Kết nối đã bị chặn.",
            ),
            name=peer,
        )
    if value == ConnectResult.VERSION_MISMATCH.value:
        return _fill(
            t(
                "Send",
                "{name} đang dùng phiên bản Teleport khác. Hãy cập nhật cả hai máy lên cùng phiên bản.",
            ),
            name=peer,
        )
    return None
