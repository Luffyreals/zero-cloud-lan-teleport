import asyncio
import contextlib
import datetime
import hashlib
import inspect
import ssl
import uuid
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from teleport.core.framing import FramingError
from teleport.net.stream import read_message, write_message
from teleport.net.tls import (
    FingerprintMismatch,
    client_context,
    peer_fingerprint,
    server_context,
    trusted_client_context,
    verify_fingerprint,
)
from teleport.trust.identity import CERT_FILE, KEY_FILE, Identity, load_or_create_identity

# X509_V_FLAG_NO_CHECK_TIME của OpenSSL (`docs/protocol.md` mục 2.1), viết số trực tiếp: không lấy từ code.
NO_CHECK_TIME = 0x200000


@pytest.fixture
def identity(tmp_path):
    return load_or_create_identity(tmp_path / "server")


async def start_echo_server(ctx: ssl.SSLContext):
    """Server trả lại mọi message, kèm fingerprint chứng chỉ client nếu có.

    `server.handled` đếm số kết nối đã bắt tay xong (asyncio chỉ gọi handler sau bắt tay).
    """
    handled: list[str | None] = []

    async def on_connect(reader, writer):
        try:
            client_fp = peer_fingerprint(writer)
        except ValueError:
            client_fp = None
        handled.append(client_fp)
        try:
            while (msg := await read_message(reader)) is not None:
                await write_message(writer, {"echo": msg, "client_fp": client_fp})
        except (ssl.SSLError, ConnectionError, FramingError):
            pass
        writer.close()

    server = await asyncio.start_server(on_connect, "127.0.0.1", 0, ssl=ctx)
    server.handled = handled
    return server, server.sockets[0].getsockname()[1]


async def round_trip(port: int, ctx: ssl.SSLContext) -> dict | None:
    """Gửi một message và đọc trả lời. None nghĩa là server đã từ chối kết nối."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port, ssl=ctx)
    try:
        await write_message(writer, {"text": "xin chào qua TLS"})
        return await asyncio.wait_for(read_message(reader), 5)
    except (ssl.SSLError, ConnectionError, FramingError):
        return None
    finally:
        writer.close()
        with contextlib.suppress(ssl.SSLError, ConnectionError):
            await writer.wait_closed()


def write_identity(
    directory: Path, *, not_before: datetime.datetime, not_after: datetime.datetime
) -> Identity:
    """Danh tính kiểu Teleport (P-256, CN `teleport-<id>`, tự ký, không extension), hiệu lực cho trước."""
    directory.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    device_id = uuid.uuid4().hex
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "teleport-" + device_id)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / CERT_FILE, directory / KEY_FILE
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    der = cert.public_bytes(serialization.Encoding.DER)
    return Identity(device_id, cert_path, key_path, hashlib.sha256(der).hexdigest())


def forge_same_name_identity(real: Identity, directory: Path) -> Identity:
    """Danh tính giả mạo `real`: cùng subject, issuer (CN `teleport-<device_id>`), serial, hạn và
    extension, nhưng **khóa khác** (tự ký bằng khóa đó). Chỉ fingerprint/khóa phân biệt được với thật."""
    directory.mkdir(parents=True, exist_ok=True)
    real_cert = x509.load_pem_x509_certificate(real.cert_path.read_bytes())
    key = ec.generate_private_key(ec.SECP256R1())
    builder = (
        x509.CertificateBuilder()
        .subject_name(real_cert.subject)
        .issuer_name(real_cert.issuer)
        .public_key(key.public_key())
        .serial_number(real_cert.serial_number)
        .not_valid_before(real_cert.not_valid_before_utc)
        .not_valid_after(real_cert.not_valid_after_utc)
    )
    for ext in real_cert.extensions:
        builder = builder.add_extension(ext.value, ext.critical)
    cert = builder.sign(key, hashes.SHA256())
    cert_path, key_path = directory / CERT_FILE, directory / KEY_FILE
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    der = cert.public_bytes(serialization.Encoding.DER)
    return Identity(real.device_id, cert_path, key_path, hashlib.sha256(der).hexdigest())


UTC = datetime.UTC
VALIDITY = {
    "expired": (datetime.datetime(2001, 1, 1, tzinfo=UTC), datetime.datetime(2002, 1, 1, tzinfo=UTC)),
    "not-yet-valid": (datetime.datetime(2090, 1, 1, tzinfo=UTC), datetime.datetime(2091, 1, 1, tzinfo=UTC)),
    "normal": (datetime.datetime(2000, 1, 1, tzinfo=UTC), datetime.datetime(9999, 12, 31, tzinfo=UTC)),
}


# --- Phía server (client dùng `cert_client`: gửi chứng chỉ mà không kiểm server) -----------------


@pytest.mark.integration
async def test_tls13_connection_exposes_server_fingerprint(identity):
    server, port = await start_echo_server(server_context(identity, [], allow_anonymous=True))
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port, ssl=client_context())
        try:
            assert writer.get_extra_info("ssl_object").version() == "TLSv1.3"
            assert peer_fingerprint(writer) == identity.fingerprint
            await write_message(writer, {"text": "xin chào qua TLS"})
            reply = await read_message(reader)
            assert reply == {"echo": {"text": "xin chào qua TLS"}, "client_fp": None}
        finally:
            writer.close()
            await writer.wait_closed()


@pytest.mark.integration
async def test_client_detects_wrong_server(identity, tmp_path):
    impostor = load_or_create_identity(tmp_path / "impostor")
    server, port = await start_echo_server(server_context(impostor, [], allow_anonymous=True))
    async with server:
        _, writer = await asyncio.open_connection("127.0.0.1", port, ssl=client_context())
        try:
            with pytest.raises(FingerprintMismatch):
                verify_fingerprint(peer_fingerprint(writer), identity.fingerprint)
        finally:
            writer.close()
            await writer.wait_closed()


@pytest.mark.integration
async def test_mtls_accepts_trusted_client_and_sees_its_fingerprint(identity, tmp_path, cert_client):
    trusted = load_or_create_identity(tmp_path / "trusted")
    server, port = await start_echo_server(server_context(identity, [trusted.cert_pem()]))
    async with server:
        reply = await round_trip(port, cert_client(trusted))
    assert reply is not None
    assert reply["client_fp"] == trusted.fingerprint


@pytest.mark.integration
@pytest.mark.parametrize("client", ["stranger", "no_cert"])
async def test_mtls_rejects_unknown_or_anonymous_client(identity, tmp_path, client, cert_client):
    trusted = load_or_create_identity(tmp_path / "trusted")
    stranger = load_or_create_identity(tmp_path / "stranger")
    ctx = cert_client(stranger) if client == "stranger" else client_context()
    server, port = await start_echo_server(server_context(identity, [trusted.cert_pem()]))
    async with server:
        assert await round_trip(port, ctx) is None


@pytest.mark.integration
async def test_mtls_with_empty_trust_list_rejects_everyone(identity, tmp_path, cert_client):
    someone = load_or_create_identity(tmp_path / "someone")
    server, port = await start_echo_server(server_context(identity, []))
    async with server:
        assert await round_trip(port, cert_client(someone)) is None


@pytest.mark.integration
async def test_single_port_accepts_trusted_and_anonymous_clients(identity, tmp_path, cert_client):
    """Một cổng (protocol.md mục 2): client tin cậy có fingerprint, client ẩn danh thì không."""
    trusted = load_or_create_identity(tmp_path / "trusted")
    ctx = server_context(identity, [trusted.cert_pem()], allow_anonymous=True)
    server, port = await start_echo_server(ctx)
    async with server:
        trusted_reply = await round_trip(port, cert_client(trusted))
        anonymous_reply = await round_trip(port, client_context())
    assert trusted_reply is not None
    assert trusted_reply["client_fp"] == trusted.fingerprint
    assert anonymous_reply is not None
    assert anonymous_reply["client_fp"] is None


@pytest.mark.integration
@pytest.mark.parametrize("trusted_list", ["one", "empty"])
async def test_single_port_still_rejects_client_with_unknown_cert(
    identity, tmp_path, trusted_list, cert_client
):
    """Gửi chứng chỉ lạ thì bị từ chối khi bắt tay, dù cổng cho phép kết nối ẩn danh."""
    trusted = load_or_create_identity(tmp_path / "trusted")
    stranger = load_or_create_identity(tmp_path / "stranger")
    certs = [trusted.cert_pem()] if trusted_list == "one" else []
    server, port = await start_echo_server(server_context(identity, certs, allow_anonymous=True))
    async with server:
        assert await round_trip(port, cert_client(stranger)) is None


@pytest.mark.integration
async def test_server_issues_no_session_ticket(identity, tmp_path):
    """Không có ticket thì không dùng lại được session để né kiểm tra sau khi bị hủy ghép đôi."""
    trusted = load_or_create_identity(tmp_path / "trusted")
    ctx = server_context(identity, [trusted.cert_pem()], allow_anonymous=True)
    assert ctx.num_tickets == 0
    server, port = await start_echo_server(ctx)
    async with server:
        client = trusted_client_context(trusted, identity.cert_pem())
        reader, writer = await asyncio.open_connection("127.0.0.1", port, ssl=client)
        try:
            await write_message(writer, {"text": "xin chào"})
            assert await asyncio.wait_for(read_message(reader), 5) is not None
            session = writer.get_extra_info("ssl_object").session
            assert session is None or not session.has_ticket
        finally:
            writer.close()
            await writer.wait_closed()


def test_server_context_accepts_pem_without_trailing_newline(identity, tmp_path):
    """PEM thiếu ký tự xuống dòng cuối không làm hỏng cả danh sách tin cậy."""
    certs = [load_or_create_identity(tmp_path / n).cert_pem().rstrip("\n") for n in ("a", "b")]
    ctx = server_context(identity, certs)
    assert ctx.cert_store_stats()["x509"] == 2  # chứng chỉ tự ký không phải CA: get_ca_certs() rỗng


@pytest.mark.parametrize("allow_anonymous", [True, False])
def test_server_context_flags(identity, allow_anonymous):
    """A3: server cũng bật NO_CHECK_TIME (kèm STRICT), vẫn TLS 1.3 và không cấp ticket."""
    ctx = server_context(identity, [], allow_anonymous=allow_anonymous)
    assert ctx.verify_flags & ssl.VERIFY_X509_STRICT
    assert ctx.verify_flags & NO_CHECK_TIME
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3
    assert ctx.num_tickets == 0
    assert ctx.verify_mode == (ssl.CERT_OPTIONAL if allow_anonymous else ssl.CERT_REQUIRED)


# --- Client ẩn danh (`client_context()`) ---------------------------------------------------------


def test_client_context_takes_no_parameters():
    """`docs/protocol.md` mục 2.1: không đường nào gửi chứng chỉ client tới server chưa kiểm."""
    assert list(inspect.signature(client_context).parameters) == []


def test_client_context_is_anonymous_cert_none():
    ctx = client_context()
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3
    assert ctx.get_ca_certs() == []


# --- Client tin cậy (`trusted_client_context`, `docs/protocol.md` mục 2.1) -------------------------


def test_trusted_client_context_flags(identity, tmp_path):
    client = load_or_create_identity(tmp_path / "client")
    ctx = trusted_client_context(client, identity.cert_pem())
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is False
    assert ctx.verify_flags & ssl.VERIFY_X509_STRICT
    assert ctx.verify_flags & NO_CHECK_TIME
    assert not ctx.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3


def test_trusted_client_context_trusts_exactly_the_stored_cert(identity, tmp_path):
    """Kho tin cậy đúng 1 chứng chỉ: không CA hệ thống, chỉ chứng chỉ đã lưu khi ghép đôi.

    Đặc tả ghi `get_ca_certs()` đúng 1, nhưng `get_ca_certs()` chỉ liệt kê chứng chỉ mà OpenSSL coi
    là CA (`X509_check_ca`); chứng chỉ Teleport không có BasicConstraints nên luôn ra `[]`. Đếm cả
    kho bằng `cert_store_stats()["x509"]`; việc ghim đúng chứng chỉ được kiểm bằng bắt tay ở dưới.
    """
    client = load_or_create_identity(tmp_path / "client")
    ctx = trusted_client_context(client, identity.cert_pem())
    stats = ctx.cert_store_stats()
    assert stats["x509"] == 1, stats
    assert stats["crl"] == 0


@pytest.mark.parametrize(
    "bad_pem",
    ["không phải PEM", "-----BEGIN CERTIFICATE-----\nđ\n-----END CERTIFICATE-----\n", None, b"PEM"],
    ids=["non-ascii", "non-ascii-inside-pem", "none", "bytes"],
)
def test_trusted_client_context_rejects_non_ascii_pem(identity, tmp_path, bad_pem):
    client = load_or_create_identity(tmp_path / "client")
    with pytest.raises(ValueError):
        trusted_client_context(client, bad_pem)


@pytest.mark.integration
async def test_trusted_client_completes_mtls_with_the_right_server(identity, tmp_path):
    client = load_or_create_identity(tmp_path / "client")
    server, port = await start_echo_server(
        server_context(identity, [client.cert_pem()], allow_anonymous=True)
    )
    async with server:
        reply = await round_trip(port, trusted_client_context(client, identity.cert_pem()))
    assert reply is not None
    assert reply["client_fp"] == client.fingerprint


@pytest.mark.integration
async def test_impostor_server_never_completes_handshake_nor_sees_client_cert(identity, tmp_path):
    """Server giả (danh tính khác, ở địa chỉ máy tin cậy, lại tin chứng chỉ client): client từ chối
    ngay trong bắt tay bằng `SSLCertVerificationError`; phía server không bao giờ bắt tay xong nên
    handler không chạy và không thấy chứng chỉ client."""
    client = load_or_create_identity(tmp_path / "client")
    impostor = load_or_create_identity(tmp_path / "impostor")
    server, port = await start_echo_server(
        server_context(impostor, [client.cert_pem()], allow_anonymous=True)
    )
    async with server:
        with pytest.raises(ssl.SSLCertVerificationError):
            await asyncio.wait_for(
                asyncio.open_connection(
                    "127.0.0.1", port, ssl=trusted_client_context(client, identity.cert_pem())
                ),
                5,
            )
        await asyncio.sleep(0.2)
        assert server.handled == [], "server giả đã bắt tay xong với client"


@pytest.mark.integration
async def test_impostor_with_same_subject_issuer_and_serial_but_other_key_fails_handshake(identity, tmp_path):
    """Server giả mang chứng chỉ **cùng subject/issuer/serial** (cùng CN `teleport-<device_id>`) với máy
    tin cậy, chỉ khác khóa: OpenSSL tra kho tin cậy theo tên sẽ thấy chứng chỉ thật, nhưng chữ ký /
    khóa không khớp → client vẫn từ chối trong bắt tay; server giả không bắt tay xong với client."""
    client = load_or_create_identity(tmp_path / "client")
    fake = forge_same_name_identity(identity, tmp_path / "fake")
    real_cert = x509.load_pem_x509_certificate(identity.cert_pem().encode("ascii"))
    fake_cert = x509.load_pem_x509_certificate(fake.cert_pem().encode("ascii"))
    assert (fake_cert.subject, fake_cert.issuer, fake_cert.serial_number) == (
        real_cert.subject,
        real_cert.issuer,
        real_cert.serial_number,
    )
    assert fake_cert.public_key().public_numbers() != real_cert.public_key().public_numbers()
    assert fake.fingerprint != identity.fingerprint
    server, port = await start_echo_server(server_context(fake, [client.cert_pem()], allow_anonymous=True))
    async with server:
        # Đối chứng: server giả là server TLS hợp lệ (client ẩn danh bắt tay xong), nên lỗi dưới là do ghim.
        assert await round_trip(port, client_context()) is not None
        assert server.handled == [None]
        with pytest.raises(ssl.SSLCertVerificationError):
            await asyncio.wait_for(
                asyncio.open_connection(
                    "127.0.0.1", port, ssl=trusted_client_context(client, identity.cert_pem())
                ),
                5,
            )
        await asyncio.sleep(0.2)
        assert server.handled == [None], "server giả đã bắt tay xong với client tin cậy"


@pytest.mark.integration
@pytest.mark.parametrize("server_validity", ["expired", "not-yet-valid", "normal"])
@pytest.mark.parametrize("client_validity", ["expired", "not-yet-valid", "normal"])
async def test_handshake_ignores_certificate_dates_both_ways(tmp_path, server_validity, client_validity):
    """A3: NO_CHECK_TIME ở cả hai chiều: chứng chỉ hết hạn / chưa hiệu lực vẫn bắt tay được, vì ghim đúng
    chứng chỉ (đồng hồ máy sai không được làm hỏng kết nối)."""
    server_id = write_identity(
        tmp_path / "s", not_before=VALIDITY[server_validity][0], not_after=VALIDITY[server_validity][1]
    )
    client_id = write_identity(
        tmp_path / "c", not_before=VALIDITY[client_validity][0], not_after=VALIDITY[client_validity][1]
    )
    server, port = await start_echo_server(
        server_context(server_id, [client_id.cert_pem()], allow_anonymous=True)
    )
    async with server:
        reply = await round_trip(port, trusted_client_context(client_id, server_id.cert_pem()))
    assert reply is not None, f"server {server_validity}, client {client_validity}: bắt tay hỏng"
    assert reply["client_fp"] == client_id.fingerprint


@pytest.mark.integration
@pytest.mark.parametrize("validity", ["expired", "not-yet-valid"])
async def test_no_check_time_does_not_loosen_pinning(identity, tmp_path, validity):
    """NO_CHECK_TIME không nới việc ghim: chứng chỉ server khác (hết hạn hay chưa hiệu lực) vẫn bị từ chối."""
    client = load_or_create_identity(tmp_path / "client")
    other = write_identity(tmp_path / "o", not_before=VALIDITY[validity][0], not_after=VALIDITY[validity][1])
    server, port = await start_echo_server(server_context(other, [client.cert_pem()], allow_anonymous=True))
    async with server:
        with pytest.raises(ssl.SSLCertVerificationError):
            await asyncio.wait_for(
                asyncio.open_connection(
                    "127.0.0.1", port, ssl=trusted_client_context(client, identity.cert_pem())
                ),
                5,
            )


FP = "ab" * 32


def test_verify_fingerprint_accepts_equal():
    verify_fingerprint(FP, FP)


@pytest.mark.parametrize(
    "other",
    ["ab" * 31 + "ac", FP[:16], FP + "ab", "", FP.upper(), "đ" * 64, "ａ" * 64, None, b"ab" * 32],
    ids=repr,
)
def test_verify_fingerprint_rejects_anything_else(other):
    """Kể cả giá trị sai dạng hay không phải ASCII: chỉ một loại lỗi cho bên gọi bắt."""
    with pytest.raises(FingerprintMismatch):
        verify_fingerprint(FP, other)
    with pytest.raises(FingerprintMismatch):
        verify_fingerprint(other, FP)
