"""SSLContext cho TLS 1.3 với chứng chỉ tự ký: ghim đúng chứng chỉ đã lưu, hai chiều (mTLS).

Chứng chỉ tự ký không được CA nào ký, nên không kiểm tra được theo kiểu HTTPS
thông thường. Thay vào đó mỗi chứng chỉ tự ký đã lưu khi ghép đôi được nạp làm trust
anchor của chính nó (docs/protocol.md mục 2.1, 2.2):

- **Client kiểm tra server** (`trusted_client_context`): chỉ nạp **đúng** chứng chỉ đã
  lưu của thiết bị cần nối, `CERT_REQUIRED`. Server đưa chứng chỉ khác thì bắt tay
  hỏng ngay ở client (`ssl.SSLCertVerificationError`), **trước** khi client gửi chứng
  chỉ của mình, nên máy giả không bao giờ thấy chứng chỉ client. Sau bắt tay `net` vẫn
  so toàn bộ fingerprint (`verify_fingerprint`) để phòng thủ thêm một lớp.
- **Server kiểm tra client** (`server_context`): nạp chứng chỉ của các thiết bị tin
  cậy làm "CA", nên client gửi chứng chỉ lạ bị từ chối ngay trong lúc bắt tay.

Cả hai chiều bật `VERIFY_X509_STRICT` và `NO_CHECK_TIME`: chứng chỉ được ghim đúng từng
byte, nên ngày hiệu lực không thêm gì về an toàn, và đồng hồ máy sai (ví dụ hết pin
CMOS) không được làm hỏng kết nối. Không dùng CA hệ thống, không `PARTIAL_CHAIN`.

Node chỉ mở **một cổng** (docs/protocol.md mục 2): `allow_anonymous=True` cho phép
client không gửi chứng chỉ; kết nối đó chỉ được dùng để ghép đôi.

Lưu ý TLS 1.3: client bị từ chối vẫn thấy `open_connection()` thành công; lỗi
chỉ lộ ra ở lần đọc đầu tiên (EOF hoặc lỗi SSL). Vì vậy client phải đọc được
`hello` của server rồi mới coi là đã kết nối.
"""

from __future__ import annotations

import asyncio
import hmac
import re
import ssl
from collections.abc import Iterable

from teleport.trust.identity import Identity, fingerprint_of_der

_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")

# X509_V_FLAG_NO_CHECK_TIME của OpenSSL (≥ 1.1.0): bỏ kiểm ngày hiệu lực khi kiểm chứng
# chỉ. Module `ssl` chưa có hằng này nên gán số trực tiếp qua `verify_flags`.
NO_CHECK_TIME = 0x200000


class FingerprintMismatch(Exception):
    pass


def server_context(
    identity: Identity, trusted_certs: Iterable[str], *, allow_anonymous: bool = False
) -> ssl.SSLContext:
    """Context phía server; `trusted_certs` là chứng chỉ PEM của các thiết bị tin cậy.

    Client gửi chứng chỉ thì chứng chỉ đó phải nằm trong `trusted_certs`, nếu không
    bắt tay thất bại (kể cả khi danh sách rỗng). Client không gửi chứng chỉ chỉ
    được nhận khi `allow_anonymous=True` (`CERT_OPTIONAL`); khi đó
    `peer_fingerprint` của kết nối raise ValueError.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(identity.cert_path, identity.key_path)
    ctx.verify_mode = ssl.CERT_OPTIONAL if allow_anonymous else ssl.CERT_REQUIRED
    ctx.verify_flags |= ssl.VERIFY_X509_STRICT | NO_CHECK_TIME
    # Không cấp session ticket: kết nối dùng lại session sẽ bỏ qua việc kiểm chứng chỉ
    # client, nên máy vừa bị hủy ghép đôi có thể vào lại bằng session cũ. Mỗi kết nối
    # đều bắt tay đầy đủ với danh sách tin cậy hiện tại (docs/protocol.md mục 2.2).
    ctx.num_tickets = 0
    # Nối bằng xuống dòng: PEM thiếu "\n" cuối sẽ dính dòng END vào dòng BEGIN của PEM sau.
    if cadata := "\n".join(trusted_certs):
        ctx.load_verify_locations(cadata=cadata)
    return ctx


def client_context() -> ssl.SSLContext:
    """Context phía client cho kết nối **ẩn danh**, chỉ dùng để ghép đôi.

    `CERT_NONE` và không nạp cặp khóa: chưa ghép đôi thì chưa có gì để kiểm chứng chỉ
    server (ghép đôi xác thực bằng mã 6 số, protocol mục 5), và client không bao giờ
    gửi chứng chỉ của mình tới một server chưa được kiểm. Kết nối điều khiển và kết nối
    dữ liệu dùng `trusted_client_context`.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def trusted_client_context(identity: Identity, server_cert_pem: str) -> ssl.SSLContext:
    """Context phía client tới một thiết bị tin cậy: server phải đưa đúng `server_cert_pem`.

    `server_cert_pem` là chứng chỉ đã lưu khi ghép đôi, làm trust anchor duy nhất (không
    nạp CA hệ thống). `CERT_REQUIRED`, `check_hostname=False` (chứng chỉ không mang tên
    máy), `VERIFY_X509_STRICT | NO_CHECK_TIME`. Chứng chỉ của `identity` chỉ được gửi sau
    khi chứng chỉ server đã qua kiểm (TLS 1.3). PEM không phải chuỗi ASCII → ValueError;
    PEM không đọc được → `ssl.SSLError`.
    """
    # `ssl` báo TypeError cho chuỗi không phải ASCII: đổi về ValueError cho đồng nhất.
    if not isinstance(server_cert_pem, str) or not server_cert_pem.isascii():
        raise ValueError("chứng chỉ server phải là chuỗi PEM ASCII")
    # Không dùng create_default_context / load_default_certs / set_default_verify_paths:
    # chỉ đúng chứng chỉ đã lưu là anchor.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.verify_flags |= ssl.VERIFY_X509_STRICT | NO_CHECK_TIME
    ctx.load_verify_locations(cadata=server_cert_pem)
    ctx.load_cert_chain(identity.cert_path, identity.key_path)
    return ctx


def peer_fingerprint(writer: asyncio.StreamWriter) -> str:
    ssl_obj: ssl.SSLObject | None = writer.get_extra_info("ssl_object")
    if ssl_obj is None:
        raise ValueError("kết nối không dùng TLS")
    der = ssl_obj.getpeercert(binary_form=True)
    if der is None:
        raise ValueError("bên kia không gửi chứng chỉ")
    return fingerprint_of_der(der)


def verify_fingerprint(actual_fp: str, expected_fp: str) -> None:
    """Raise FingerprintMismatch nếu hai fingerprint (64 ký tự hex thường) khác nhau.

    Luôn so **toàn bộ** fingerprint, không so tiền tố. Giá trị không đúng dạng (kể cả
    chuỗi không phải ASCII) cũng là không khớp, để bên gọi chỉ phải bắt một loại lỗi.
    """
    for fp in (actual_fp, expected_fp):
        if not isinstance(fp, str) or not _FINGERPRINT_RE.fullmatch(fp):
            raise FingerprintMismatch("fingerprint phải là đúng 64 ký tự hex thường")
    # compare_digest so sánh trong thời gian không đổi, không lộ vị trí ký tự sai.
    if not hmac.compare_digest(actual_fp.encode("ascii"), expected_fp.encode("ascii")):
        raise FingerprintMismatch("fingerprint của máy bên kia KHÔNG khớp với fingerprint đã lưu")
