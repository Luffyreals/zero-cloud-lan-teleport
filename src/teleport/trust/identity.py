"""Danh tính thiết bị: một khóa ECDSA P-256 và chứng chỉ tự ký.

Fingerprint = SHA-256 của chứng chỉ ở dạng DER. Đây là "số căn cước" của máy:
ghép đôi thực chất là hai máy lưu chứng chỉ (và fingerprint) của nhau.

Khi ghép đôi, bên khởi xướng ký `core.pairing_code.proof_payload` bằng khóa danh tính
(`PairingSigner`) và bên trả lời kiểm chữ ký đó bằng chứng chỉ trong `pair_request`
(`verify_pairing_proof`), protocol mục 5.1, 5.2.
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import re
import string
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from cryptography.x509.oid import NameOID, SignatureAlgorithmOID

from teleport.core.pairing_code import PROOF_SIGNATURE_SIZE
from teleport.lock import NodeLock, NodeLockedError
from teleport.paths import TRUSTED_FILE

CERT_FILE = "device.crt"
KEY_FILE = "device.key"
CN_PREFIX = "teleport-"
IDENTITY_LOCK = "identity.lock"
# Thư mục tạm riêng (0o700) chứa khóa riêng lúc đang ghi, xem `_create_identity`.
KEY_STAGING_DIR = "identity.tmp"

_LOCK_WAIT = 10.0  # giây chờ tiến trình khác tạo xong danh tính

# Giới hạn độ dài PEM của chứng chỉ nhận từ máy khác (bằng MAX_CERT_PEM_LEN ở core.messages).
MAX_PEM_LEN = 8192
PEM_BEGIN = "-----BEGIN CERTIFICATE-----"
PEM_END = "-----END CERTIFICATE-----"

# Extension cũ của Netscape đánh dấu loại chứng chỉ (có bit "SSL CA"); OpenSSL vẫn đọc nó.
_NETSCAPE_CERT_TYPE = x509.ObjectIdentifier("2.16.840.1.113730.1.1")

_CN_RE = re.compile(re.escape(CN_PREFIX) + r"[0-9a-f]{32}")

# Bậc n của nhóm điểm P-256 (SEC 2): r và s của chữ ký hợp lệ nằm trong 1…n−1.
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_SCALAR_SIZE = PROOF_SIGNATURE_SIZE // 2  # 32 byte mỗi số r, s


@dataclass(frozen=True)
class Identity:
    device_id: str
    cert_path: Path
    key_path: Path
    fingerprint: str  # 64 ký tự hex thường

    @property
    def short_fingerprint(self) -> str:
        """8 byte đầu, dạng "AB:CD:...": đủ ngắn để đọc và so bằng mắt."""
        return format_fingerprint(self.fingerprint[:16])

    def cert_pem(self) -> str:
        """Chứng chỉ dạng PEM: thứ được trao cho thiết bị khác khi ghép đôi."""
        return self.cert_path.read_text(encoding="ascii")


def fingerprint_of_der(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def format_fingerprint(hex_fp: str) -> str:
    hex_fp = hex_fp.upper()
    return ":".join(hex_fp[i : i + 2] for i in range(0, len(hex_fp), 2))


class InvalidCertificate(ValueError):
    """Chứng chỉ của máy khác không hợp lệ hoặc không phải chứng chỉ thiết bị Teleport.

    Mọi lỗi khi phân tích hay kiểm chứng chỉ đều thành lỗi này (protocol §5.1).
    `cryptography` ném nhiều lớp lỗi không chung gốc, tùy phiên bản và tùy lúc load hay
    lúc đọc thuộc tính (ví dụ InvalidVersion, DuplicateExtension, hay
    UnsupportedGeneralNameType với SAN x400Address/EDIPartyName, kế thừa thẳng từ
    Exception), nên các chỗ phân tích bắt `Exception` thay vì liệt kê từng lớp.
    """


@dataclass(frozen=True)
class PeerCert:
    """Chứng chỉ của một máy khác, đã được kiểm tra."""

    device_id: str
    fingerprint: str  # 64 ký tự hex thường
    pem: str  # PEM đã chuẩn hóa (serialize lại từ chứng chỉ đã phân tích)


def peer_cert_from_pem(pem: str) -> PeerCert:
    """Phân tích và kiểm tra chứng chỉ PEM nhận từ máy khác (ví dụ trong `pair_request`).

    Chỉ nhận chuỗi ASCII ≤ 8192 ký tự chứa đúng một khối CERTIFICATE; ngoài khối
    chỉ được có khoảng trắng. Sai bất kỳ điều kiện nào → InvalidCertificate.
    """
    if not isinstance(pem, str):
        raise InvalidCertificate("chứng chỉ PEM phải là chuỗi")
    if len(pem) > MAX_PEM_LEN:
        raise InvalidCertificate(f"chứng chỉ PEM dài quá {MAX_PEM_LEN} ký tự")
    if not pem.isascii():
        raise InvalidCertificate("chứng chỉ PEM chỉ được chứa ký tự ASCII")
    return _peer_cert(_parse_pem(pem))


def _parse_pem(pem: str) -> x509.Certificate:
    """Kiểm dạng PEM rồi phân tích; chưa kiểm nội dung chứng chỉ (việc của `_peer_cert`)."""
    body = pem.strip(string.whitespace)
    if not (
        body.startswith(PEM_BEGIN)
        and body.endswith(PEM_END)
        and body.count("-----BEGIN") == 1
        and body.count("-----END") == 1
    ):
        raise InvalidCertificate("cần đúng một khối CERTIFICATE, ngoài khối chỉ được có khoảng trắng")
    try:
        return x509.load_pem_x509_certificate(body.encode("ascii"))
    except Exception as e:  # mọi lỗi của `cryptography`, xem InvalidCertificate
        raise InvalidCertificate("không phân tích được chứng chỉ PEM") from e


def peer_cert_from_der(der: bytes) -> PeerCert:
    """Như `peer_cert_from_pem`, cho chứng chỉ DER (ví dụ lấy từ bắt tay TLS)."""
    if not isinstance(der, bytes):
        raise InvalidCertificate("chứng chỉ DER phải là bytes")
    if len(der) > MAX_PEM_LEN:
        raise InvalidCertificate(f"chứng chỉ DER dài quá {MAX_PEM_LEN} byte")
    try:
        cert = x509.load_der_x509_certificate(der)
    except Exception as e:  # mọi lỗi của `cryptography`, xem InvalidCertificate
        raise InvalidCertificate("không phân tích được chứng chỉ DER") from e
    return _peer_cert(cert)


def _reject_ca_markers(cert: x509.Certificate) -> None:
    """Từ chối mọi dấu hiệu chứng chỉ CA.

    Chứng chỉ tin cậy được nạp làm trust anchor cho mTLS. OpenSSL coi một chứng chỉ
    là CA không chỉ qua BasicConstraints CA=true mà cả qua KeyUsage (keyCertSign,
    cRLSign) hay Netscape Cert Type; nhận chúng thì chứng chỉ đó có thể ký ra chứng
    chỉ giả cho thiết bị khác. Chứng chỉ do `_create_identity` tạo không có extension.
    """
    extensions = cert.extensions
    try:
        constraints = extensions.get_extension_for_class(x509.BasicConstraints).value
    except x509.ExtensionNotFound:
        pass
    else:
        if constraints.ca:
            raise InvalidCertificate("không nhận chứng chỉ CA (BasicConstraints CA=true)")
    try:
        usage = extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound:
        pass
    else:
        if usage.key_cert_sign or usage.crl_sign:
            raise InvalidCertificate("không nhận chứng chỉ CA (KeyUsage keyCertSign/cRLSign)")
    try:
        extensions.get_extension_for_oid(_NETSCAPE_CERT_TYPE)
    except x509.ExtensionNotFound:
        pass
    else:
        raise InvalidCertificate("không nhận chứng chỉ có extension Netscape Cert Type")


def _peer_cert(cert: x509.Certificate) -> PeerCert:
    """Kiểm tra chứng chỉ đúng dạng một thiết bị Teleport (như `_create_identity` tạo ra)."""
    try:
        if cert.version != x509.Version.v3:
            raise InvalidCertificate("chứng chỉ phải là X.509 v3")
        cns = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if len(cns) != 1:
            raise InvalidCertificate("subject phải có đúng một CN")
        cn = cns[0].value
        if not isinstance(cn, str) or not _CN_RE.fullmatch(cn):
            raise InvalidCertificate("CN phải có dạng teleport-<32 ký tự hex thường>")
        if cert.issuer != cert.subject:
            raise InvalidCertificate("chứng chỉ phải tự ký (issuer trùng subject)")
        if cert.signature_algorithm_oid != SignatureAlgorithmOID.ECDSA_WITH_SHA256:
            raise InvalidCertificate("chữ ký phải là ECDSA-SHA256")
        key = cert.public_key()
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise InvalidCertificate("khóa phải là ECDSA P-256")
        _reject_ca_markers(cert)
        cert.verify_directly_issued_by(cert)
        der = cert.public_bytes(serialization.Encoding.DER)
        pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    except InvalidCertificate:
        raise
    except Exception as e:  # mọi lỗi của `cryptography`, xem InvalidCertificate
        raise InvalidCertificate("chứng chỉ không hợp lệ hoặc chữ ký tự ký sai") from e
    if len(pem) > MAX_PEM_LEN:
        raise InvalidCertificate(f"chứng chỉ PEM dài quá {MAX_PEM_LEN} ký tự")
    return PeerCert(device_id=cn.removeprefix(CN_PREFIX), fingerprint=fingerprint_of_der(der), pem=pem)


class IdentityError(Exception):
    """Danh tính của chính máy này bị thiếu một nửa, hỏng hoặc không khớp nhau.

    Không bao giờ tự tạo danh tính mới để thay: làm vậy sẽ âm thầm xóa mọi ghép đôi.
    """


# Hiệu lực từ một ngày cố định trong quá khứ tới "không bao giờ hết hạn" (RFC 5280
# mục 4.1.2.5). OpenSSL kiểm ngày hiệu lực của chứng chỉ client khi bắt tay mTLS, nên
# không ngày nào được phụ thuộc đồng hồ của máy tạo: máy hết pin CMOS (đồng hồ về năm
# 2000) vẫn phải tạo được chứng chỉ mà máy khác chấp nhận, và danh tính không hết hạn.
_NOT_VALID_BEFORE = datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC)
_NOT_VALID_AFTER = datetime.datetime(9999, 12, 31, 23, 59, 59, tzinfo=datetime.UTC)


def load_or_create_identity(config_dir: Path) -> Identity:
    """Đọc danh tính trong `config_dir`, hoặc tạo mới nếu chưa có cả hai file.

    Chỉ còn một trong hai file, file hỏng, hay khóa không khớp chứng chỉ → IdentityError.
    Không có danh tính mà vẫn còn `trusted.json` → IdentityError (tạo mới sẽ âm thầm
    làm hỏng mọi ghép đôi). Việc tạo chạy trong khi giữ `identity.lock`, nên nhiều tiến
    trình chạy lần đầu cùng lúc đều nhận cùng một danh tính.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    cert_path = config_dir / CERT_FILE
    key_path = config_dir / KEY_FILE
    if not (cert_path.exists() and key_path.exists()):
        with _creation_lock(config_dir):
            _create_or_finish(config_dir, cert_path, key_path)
    return _load_identity(config_dir, cert_path, key_path)


@contextmanager
def _creation_lock(config_dir: Path) -> Iterator[None]:
    lock = NodeLock(config_dir, IDENTITY_LOCK)
    try:
        lock.acquire(timeout=_LOCK_WAIT)
    except NodeLockedError as e:
        message = f"Tiến trình khác đang tạo danh tính trong {config_dir}; hãy chạy lại lệnh"
        raise IdentityError(message) from e
    try:
        yield
    finally:
        lock.release()


def _create_or_finish(config_dir: Path, cert_path: Path, key_path: Path) -> None:
    """Chỉ gọi khi đang giữ `identity.lock`: không tiến trình nào khác tạo cùng lúc."""
    cert_tmp = _tmp_path(cert_path)
    has_cert, has_key = cert_path.exists(), key_path.exists()
    if has_cert and has_key:
        return  # tiến trình khác vừa tạo xong trong lúc ta chờ khóa
    if not has_cert and not has_key:
        if _may_have_pairings(config_dir / TRUSTED_FILE):
            raise _identity_error(config_dir, f"không có danh tính nhưng {TRUSTED_FILE} vẫn còn thiết bị")
        _create_identity(cert_path, key_path)
    elif has_key and cert_tmp.exists():
        # Lần tạo trước bị ngắt giữa hai bước đổi tên; _load_identity kiểm khóa khớp chứng chỉ.
        os.replace(cert_tmp, cert_path)
        with contextlib.suppress(OSError):  # chỉ là dọn rác: không chặn việc nạp danh tính
            _remove_key_staging(config_dir)
    # Các trường hợp còn lại (thiếu một nửa): _load_identity báo IdentityError.


def _may_have_pairings(path: Path) -> bool:
    """False chỉ khi chắc chắn chưa ghép đôi với ai: không có file, hoặc danh sách thiết bị rỗng.

    File không đọc được hay hỏng → True: thà báo lỗi còn hơn âm thầm làm hỏng ghép đôi.
    Kiểm chi tiết từng mục là việc của `teleport.trust.store`.
    """
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except FileNotFoundError:
        return False
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return True
    return not (isinstance(data, dict) and data.get("devices") == [])


def _identity_error(config_dir: Path, detail: str) -> IdentityError:
    return IdentityError(
        f"Danh tính thiết bị trong {config_dir} bị hỏng hoặc thiếu ({detail}). "
        f"Nếu muốn tạo danh tính mới, hãy xóa {CERT_FILE}, {KEY_FILE} và {TRUSTED_FILE} "
        "trong thư mục đó; các máy đã ghép đôi sẽ phải ghép đôi lại."
    )


def _load_identity(config_dir: Path, cert_path: Path, key_path: Path) -> Identity:
    for path in (cert_path, key_path):
        if not path.exists():
            raise _identity_error(config_dir, f"không có {path.name}")
    try:
        cert_text = cert_path.read_text(encoding="ascii")
        key_bytes = key_path.read_bytes()
    except (OSError, UnicodeDecodeError) as e:
        raise _identity_error(config_dir, f"không đọc được: {e}") from e
    try:
        # Chứng chỉ của chính mình phải qua đúng bộ kiểm tra dành cho máy khác.
        cert = _parse_pem(cert_text)
        own = _peer_cert(cert)
    except InvalidCertificate as e:
        raise _identity_error(config_dir, f"{CERT_FILE}: {e}") from e
    _load_key(config_dir, key_bytes, cert)
    return Identity(
        device_id=own.device_id,
        cert_path=cert_path,
        key_path=key_path,
        fingerprint=own.fingerprint,
    )


def _load_key(config_dir: Path, key_bytes: bytes, cert: x509.Certificate) -> ec.EllipticCurvePrivateKey:
    """Khóa riêng PEM, phải là ECDSA P-256 và khớp khóa công khai của `cert`; sai → IdentityError."""
    try:
        key = serialization.load_pem_private_key(key_bytes, password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm) as e:
        raise _identity_error(config_dir, f"{KEY_FILE} không phải khóa PEM hợp lệ") from e
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise _identity_error(config_dir, f"{KEY_FILE} không phải khóa ECDSA P-256")
    if key.public_key() != cert.public_key():
        raise _identity_error(config_dir, f"{KEY_FILE} không khớp {CERT_FILE}")
    return key


# ---- Chứng minh giữ khóa khi ghép đôi (protocol mục 5.1, 5.2) ------------------------------


class PairingSigner:
    """Ký payload chứng minh giữ khóa (`core.pairing_code.proof_payload`) bằng khóa danh tính.

    Tạo bằng `load_pairing_signer`. Chữ ký là ECDSA P-256 + SHA-256, dạng r ‖ s, mỗi số
    32 byte big-endian (IEEE P1363). `repr` không lộ khóa.
    """

    __slots__ = ("_key", "device_id")

    def __init__(self, key: ec.EllipticCurvePrivateKey, device_id: str) -> None:
        self._key = key
        self.device_id = device_id

    def sign(self, payload: bytes) -> bytes:
        """Chữ ký PROOF_SIGNATURE_SIZE (64) byte trên `payload`; `payload` không phải bytes → TypeError."""
        if not isinstance(payload, bytes):
            raise TypeError("payload phải là bytes")
        r, s = decode_dss_signature(self._key.sign(payload, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(_SCALAR_SIZE, "big") + s.to_bytes(_SCALAR_SIZE, "big")

    def __repr__(self) -> str:
        return f"PairingSigner(device_id={self.device_id!r})"


def load_pairing_signer(identity: Identity) -> PairingSigner:
    """Đọc khóa riêng của `identity` để ký khi ghép đôi.

    Đọc lại cả hai file: chứng chỉ phải đúng là chứng chỉ của `identity` (cùng
    fingerprint), khóa phải là ECDSA P-256 và khớp khóa công khai trong chứng chỉ. Không
    đọc được, file hỏng, khóa sai hay không khớp → IdentityError.
    """
    config_dir = identity.key_path.parent
    try:
        cert_text = identity.cert_path.read_text(encoding="ascii")
        key_bytes = identity.key_path.read_bytes()
    except (OSError, UnicodeDecodeError) as e:
        raise _identity_error(config_dir, f"không đọc được: {e}") from e
    try:
        cert = _parse_pem(cert_text)
        own = _peer_cert(cert)
    except InvalidCertificate as e:
        raise _identity_error(config_dir, f"{CERT_FILE}: {e}") from e
    if own.fingerprint != identity.fingerprint:
        raise _identity_error(config_dir, f"{CERT_FILE} đã đổi từ lúc nạp danh tính")
    return PairingSigner(_load_key(config_dir, key_bytes, cert), identity.device_id)


def verify_pairing_proof(peer: PeerCert, payload: bytes, signature: bytes) -> bool:
    """True chỉ khi `signature` (64 byte r ‖ s) là chữ ký đúng trên `payload` bằng khóa của `peer`.

    Không bao giờ raise: sai kiểu, chữ ký khác 64 byte, r hoặc s ngoài 1…n−1, chứng chỉ
    không đọc được hay khóa không phải P-256, chữ ký sai, hay bất kỳ lỗi nào khác → False.
    Không chặn chữ ký high-s (protocol mục 5.2).
    """
    try:
        if (
            not isinstance(peer, PeerCert)
            or not isinstance(payload, bytes)
            or not isinstance(signature, bytes)
        ):
            return False
        if len(signature) != PROOF_SIGNATURE_SIZE:
            return False
        r = int.from_bytes(signature[:_SCALAR_SIZE], "big")
        s = int.from_bytes(signature[_SCALAR_SIZE:], "big")
        if not (0 < r < _P256_ORDER and 0 < s < _P256_ORDER):
            return False
        cert = x509.load_pem_x509_certificate(peer.pem.encode("ascii"))
        if fingerprint_of_der(cert.public_bytes(serialization.Encoding.DER)) != peer.fingerprint:
            return False
        key = cert.public_key()
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            return False
        key.verify(encode_dss_signature(r, s), payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return False
    except Exception:  # mọi lỗi của `cryptography` (xem InvalidCertificate): coi là chữ ký sai
        return False
    return True


def _create_identity(cert_path: Path, key_path: Path) -> None:
    """Ghi cả hai file ra `.tmp`, rồi đổi tên khóa trước, chứng chỉ sau. Gọi khi giữ `identity.lock`.

    Khóa được ghi trong thư mục tạm riêng `KEY_STAGING_DIR` tạo bằng `os.mkdir(..., 0o700)`.
    Trên Windows quyền 0o600 của file không có tác dụng, còn từ Python 3.12.4 mode 0o700 của
    `mkdir` gắn một DACL được bảo vệ (chỉ SYSTEM, Administrators, OWNER RIGHTS); khóa kế thừa
    DACL đó và `os.replace` trong cùng ổ giữ nguyên nó, nên khóa không mang ACL của thư mục
    cấu hình (có thể là thư mục dùng chung chọn bằng `--config-dir`). Python cũ hơn: khóa kế
    thừa ACL của thư mục cấu hình như trước.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CN_PREFIX + uuid.uuid4().hex)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)  # tự ký: người cấp chính là chủ thể
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_NOT_VALID_BEFORE)
        .not_valid_after(_NOT_VALID_AFTER)
        .sign(key, hashes.SHA256())
    )
    # Khóa riêng lưu dạng chưa mã hóa cho đơn giản; chỉ chủ sở hữu đọc được (Windows: xem docstring).
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    config_dir = key_path.parent
    _remove_key_staging(config_dir)  # còn sót từ lần tạo bị ngắt: tạo lại để chắc có DACL mới
    staging = config_dir / KEY_STAGING_DIR
    os.mkdir(staging, 0o700)
    key_tmp, cert_tmp = staging / _tmp_path(key_path).name, _tmp_path(cert_path)
    _write_durable(key_tmp, key_pem, 0o600)  # khóa riêng: chỉ chủ sở hữu đọc được
    _write_durable(cert_tmp, cert.public_bytes(serialization.Encoding.PEM), 0o644)  # chứng chỉ công khai
    os.replace(key_tmp, key_path)
    staging.rmdir()
    os.replace(cert_tmp, cert_path)


def _remove_key_staging(config_dir: Path) -> None:
    """Xóa `KEY_STAGING_DIR` (và khóa `.tmp` bên trong) nếu có; có thứ khác bên trong → OSError."""
    staging = config_dir / KEY_STAGING_DIR
    (staging / _tmp_path(Path(KEY_FILE)).name).unlink(missing_ok=True)
    with contextlib.suppress(FileNotFoundError):
        staging.rmdir()


def _tmp_path(path: Path) -> Path:
    return path.with_name(path.name + ".tmp")


def _write_durable(path: Path, content: bytes, mode: int) -> None:
    """Ghi file với quyền `mode` ngay từ lúc tạo (POSIX), rồi fsync.

    Không có lúc nào file mang quyền rộng hơn `mode`: với khóa riêng (0o600) nghĩa là
    không có khoảnh khắc người khác đọc được.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), mode)
    with os.fdopen(fd, "wb") as f:
        if sys.platform != "win32":
            os.fchmod(f.fileno(), mode)  # .tmp còn sót từ lần trước có thể mang quyền khác
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
