import base64
import dataclasses
import datetime
import functools
import os
import re
import ssl
import subprocess
import sys
import textwrap

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtensionOID
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from support import windows_dacl

from teleport.trust import store
from teleport.trust.identity import (
    CERT_FILE,
    IDENTITY_LOCK,
    KEY_FILE,
    KEY_STAGING_DIR,
    IdentityError,
    InvalidCertificate,
    PeerCert,
    fingerprint_of_der,
    format_fingerprint,
    load_or_create_identity,
    peer_cert_from_der,
    peer_cert_from_pem,
)

MAX_PEM = 8192


def pem_of(cert: x509.Certificate) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def der_of(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.DER)


def test_creates_identity_files(tmp_path):
    identity = load_or_create_identity(tmp_path / "cfg")
    assert identity.cert_path.exists()
    assert identity.key_path.exists()
    assert re.fullmatch(r"[0-9a-f]{64}", identity.fingerprint)
    assert re.fullmatch(r"[0-9a-f]{32}", identity.device_id)


def test_reload_returns_same_identity(tmp_path):
    first = load_or_create_identity(tmp_path)
    second = load_or_create_identity(tmp_path)
    assert first == second


def test_each_device_gets_its_own_identity(tmp_path):
    a = load_or_create_identity(tmp_path / "a")
    b = load_or_create_identity(tmp_path / "b")
    assert a.fingerprint != b.fingerprint
    assert a.device_id != b.device_id


def test_format_fingerprint():
    assert format_fingerprint("abcd12") == "AB:CD:12"


def test_short_fingerprint_is_first_8_bytes(tmp_path):
    identity = load_or_create_identity(tmp_path)
    short = identity.short_fingerprint
    assert len(short) == 23  # 8 cặp hex + 7 dấu ":"
    assert short.replace(":", "").lower() == identity.fingerprint[:16]


def test_cert_pem_matches_fingerprint(tmp_path):
    identity = load_or_create_identity(tmp_path)
    pem = identity.cert_pem()
    assert pem.startswith("-----BEGIN CERTIFICATE-----")
    assert fingerprint_of_der(ssl.PEM_cert_to_DER_cert(pem)) == identity.fingerprint


# --- Danh tính của chính máy này: không bao giờ âm thầm tạo lại -------------------------------------


def test_cert_validity_does_not_depend_on_local_clock(tmp_path):
    """Máy lệch đồng hồ vẫn tạo được chứng chỉ mà máy khác chấp nhận, và không bao giờ hết hạn."""
    identity = load_or_create_identity(tmp_path)
    cert = x509.load_pem_x509_certificate(identity.cert_path.read_bytes())
    assert cert.not_valid_before_utc == datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC)
    assert cert.not_valid_after_utc == datetime.datetime(9999, 12, 31, 23, 59, 59, tzinfo=datetime.UTC)


def test_no_tmp_files_left_after_create(tmp_path):
    load_or_create_identity(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([CERT_FILE, KEY_FILE, IDENTITY_LOCK])


@pytest.mark.skipif(os.name != "posix", reason="quyền file kiểu POSIX")
def test_key_file_is_owner_only_and_cert_is_public(tmp_path):
    identity = load_or_create_identity(tmp_path)
    assert identity.key_path.stat().st_mode & 0o777 == 0o600
    assert identity.cert_path.stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize("missing", [CERT_FILE, KEY_FILE])
def test_half_missing_identity_is_error_not_regenerated(tmp_path, missing):
    load_or_create_identity(tmp_path)
    (tmp_path / missing).unlink()
    with pytest.raises(IdentityError, match=missing):
        load_or_create_identity(tmp_path)
    assert not (tmp_path / missing).exists()


@pytest.mark.parametrize(
    ("victim", "content"),
    [
        (CERT_FILE, b"garbage"),
        (CERT_FILE, b""),
        (KEY_FILE, b"garbage"),
        (KEY_FILE, bytes([0xFF, 0xFE])),
    ],
)
def test_corrupt_identity_file_is_error(tmp_path, victim, content):
    load_or_create_identity(tmp_path)
    (tmp_path / victim).write_bytes(content)
    with pytest.raises(IdentityError, match=victim):
        load_or_create_identity(tmp_path)


def test_key_not_matching_cert_is_error(tmp_path):
    load_or_create_identity(tmp_path / "a")
    load_or_create_identity(tmp_path / "b")
    (tmp_path / "a" / KEY_FILE).write_bytes((tmp_path / "b" / KEY_FILE).read_bytes())
    with pytest.raises(IdentityError, match="không khớp"):
        load_or_create_identity(tmp_path / "a")


def test_non_p256_key_is_error(tmp_path):
    load_or_create_identity(tmp_path)
    other = ec.generate_private_key(ec.SECP384R1())
    (tmp_path / KEY_FILE).write_bytes(
        other.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    with pytest.raises(IdentityError, match="P-256"):
        load_or_create_identity(tmp_path)


def test_interrupted_create_is_completed(tmp_path):
    """Bị ngắt sau khi đổi tên khóa, trước khi đổi tên chứng chỉ: lần sau làm nốt."""
    original = load_or_create_identity(tmp_path)
    (tmp_path / CERT_FILE).rename(tmp_path / (CERT_FILE + ".tmp"))
    assert load_or_create_identity(tmp_path) == original
    assert not (tmp_path / (CERT_FILE + ".tmp")).exists()


def test_interrupted_create_removes_leftover_key_staging(tmp_path):
    """Bị ngắt sau khi đổi tên khóa, trước khi xóa thư mục tạm của khóa: lần sau dọn nốt."""
    original = load_or_create_identity(tmp_path)
    (tmp_path / CERT_FILE).rename(tmp_path / (CERT_FILE + ".tmp"))
    (tmp_path / KEY_STAGING_DIR).mkdir()
    assert load_or_create_identity(tmp_path) == original
    assert not (tmp_path / KEY_STAGING_DIR).exists()


def test_leftover_key_staging_does_not_block_first_create(tmp_path):
    """Bị ngắt khi khóa còn trong thư mục tạm: lần sau tạo lại thư mục đó và tạo danh tính mới."""
    staging = tmp_path / KEY_STAGING_DIR
    staging.mkdir()
    (staging / (KEY_FILE + ".tmp")).write_bytes(b"old")
    load_or_create_identity(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([CERT_FILE, KEY_FILE, IDENTITY_LOCK])


@pytest.mark.skipif(
    sys.platform != "win32" or sys.version_info < (3, 12, 4),
    reason="DACL được bảo vệ của os.mkdir(0o700) chỉ có trên Windows, từ Python 3.12.4",
)
def test_key_does_not_inherit_shared_config_dir_acl_on_windows(tmp_path):
    # Thư mục cấu hình dùng chung (--config-dir): cấp quyền đọc cho BUILTIN\Users (BU).
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    icacls = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "icacls.exe")
    subprocess.run(
        [icacls, str(cfg), "/grant", "*S-1-5-32-545:(OI)(CI)(RX)"], check=True, capture_output=True
    )
    identity = load_or_create_identity(cfg)
    # Đối chứng: chứng chỉ công khai kế thừa ACL của thư mục, kể cả ACE vừa cấp.
    cert_protected, cert_sddl = windows_dacl(identity.cert_path)
    assert not cert_protected
    assert ";;;BU)" in cert_sddl
    key_protected, key_sddl = windows_dacl(identity.key_path)
    assert key_protected, key_sddl
    assert ";;;BU)" not in key_sddl
    assert ";;;OW)" in key_sddl  # OWNER RIGHTS: chủ vẫn đọc được


def test_cert_with_only_key_tmp_is_error_not_completed(tmp_path):
    """Chỉ có chứng chỉ (khóa còn ở .tmp) không bao giờ xảy ra khi tạo bình thường: báo lỗi."""
    load_or_create_identity(tmp_path)
    (tmp_path / KEY_FILE).rename(tmp_path / (KEY_FILE + ".tmp"))
    with pytest.raises(IdentityError, match=KEY_FILE):
        load_or_create_identity(tmp_path)


def _wipe_identity(cfg):
    (cfg / CERT_FILE).unlink()
    (cfg / KEY_FILE).unlink()


@pytest.mark.parametrize(
    "content",
    [
        '{"version": 1, "devices": [{"device_id": "x"}]}',  # còn thiết bị (không cần hợp lệ)
        "không phải JSON",  # hỏng: không chắc là rỗng, nên không đánh liều
        '{"version": 1}',
        '["devices"]',
    ],
)
def test_missing_identity_with_possible_pairings_is_error(tmp_path, content):
    """Mất cả hai file nhưng trusted.json có thể còn thiết bị: tạo mới sẽ làm hỏng ghép đôi."""
    load_or_create_identity(tmp_path)
    (tmp_path / store.TRUSTED_FILE).write_text(content, encoding="utf-8")
    _wipe_identity(tmp_path)
    with pytest.raises(IdentityError, match=store.TRUSTED_FILE):
        load_or_create_identity(tmp_path)
    assert not (tmp_path / CERT_FILE).exists()


@pytest.mark.parametrize("bom", ["", "\ufeff"])
def test_missing_identity_with_empty_trust_store_creates_new(tmp_path, bom):
    """Đã hủy ghép đôi hết (trusted.json còn nhưng rỗng): không có gì để mất, được tạo mới."""
    old = load_or_create_identity(tmp_path)
    (tmp_path / store.TRUSTED_FILE).write_text(bom + '{"version": 1, "devices": []}', encoding="utf-8")
    _wipe_identity(tmp_path)
    assert load_or_create_identity(tmp_path).fingerprint != old.fingerprint


# Tiến trình con import xong thì báo "ready" rồi chờ file "go", để mọi tiến trình
# cùng gọi load_or_create_identity gần như một lúc (khởi động Python lâu hơn nhiều so
# với việc tạo danh tính, nên không có rào chắn này thì chúng chạy lần lượt).
CHILD_CREATE = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from teleport.trust.identity import load_or_create_identity
    go = Path(sys.argv[2])
    print("ready", flush=True)
    while not go.exists():
        time.sleep(0.001)
    print(load_or_create_identity(Path(sys.argv[1])).fingerprint, flush=True)
    """
)


def test_concurrent_first_run_yields_one_identity(tmp_path):
    """Nhiều tiến trình chạy lần đầu cùng lúc đều nhận cùng một danh tính hợp lệ."""
    cfg = tmp_path / "cfg"
    go = tmp_path / "go"
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", CHILD_CREATE, str(cfg), str(go)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(6)
    ]
    for p in procs:
        assert p.stdout.readline().strip() == "ready", p.stderr.read()
    go.touch()
    results = [p.communicate(timeout=60) for p in procs]
    assert all(p.returncode == 0 for p in procs), [err for _, err in results]
    fingerprints = {out.strip() for out, _ in results}
    assert fingerprints == {load_or_create_identity(cfg).fingerprint}


def test_stale_tmp_files_do_not_block_first_create(tmp_path):
    """Bị ngắt trước bước đổi tên nào: chỉ còn .tmp, coi như chưa có danh tính."""
    (tmp_path / (KEY_FILE + ".tmp")).write_bytes(b"old")
    (tmp_path / (CERT_FILE + ".tmp")).write_bytes(b"old")
    identity = load_or_create_identity(tmp_path)
    assert load_or_create_identity(tmp_path) == identity


# --- PeerCert: chứng chỉ hợp lệ ----------------------------------------------------------------


@pytest.fixture
def identity(tmp_path):
    return load_or_create_identity(tmp_path / "peer")


def test_invalid_certificate_is_value_error():
    assert issubclass(InvalidCertificate, ValueError)


def test_peer_cert_from_pem_of_own_identity(identity):
    peer = peer_cert_from_pem(identity.cert_pem())
    assert isinstance(peer, PeerCert)
    assert peer.device_id == identity.device_id
    assert peer.fingerprint == identity.fingerprint
    assert peer.pem == identity.cert_pem()  # bất biến của phụ lục điểm 6


def test_peer_cert_from_der_of_own_identity(identity):
    der = ssl.PEM_cert_to_DER_cert(identity.cert_pem())
    peer = peer_cert_from_der(der)
    assert peer == peer_cert_from_pem(identity.cert_pem())
    assert peer.pem == identity.cert_pem()
    assert peer.fingerprint == fingerprint_of_der(der)


def test_peer_cert_is_frozen(identity):
    peer = peer_cert_from_pem(identity.cert_pem())
    with pytest.raises(dataclasses.FrozenInstanceError):
        peer.device_id = "0" * 32  # type: ignore[misc]


@pytest.mark.parametrize(
    ("prefix", "suffix"),
    [("\n\n  ", "  \n"), ("\t", ""), ("", "\r\n\r\n"), (" \r\n", "\n\t \n")],
    ids=["nl-space", "tab", "crlf", "mixed"],
)
def test_pem_with_surrounding_whitespace_is_valid_and_normalized(identity, prefix, suffix):
    peer = peer_cert_from_pem(prefix + identity.cert_pem() + suffix)
    assert peer.device_id == identity.device_id
    assert peer.fingerprint == identity.fingerprint
    assert peer.pem == identity.cert_pem()


def test_self_made_teleport_cert_is_valid(make_cert):
    # Đối chứng: cert tự tạo đúng chuẩn thì phải hợp lệ (để các ca xấu bên dưới có ý nghĩa).
    cert = make_cert(cn="teleport-" + "ab" * 16)
    peer = peer_cert_from_pem(pem_of(cert))
    assert peer.device_id == "ab" * 16
    assert peer.fingerprint == fingerprint_of_der(der_of(cert))
    assert peer.pem == pem_of(cert)
    assert peer_cert_from_der(der_of(cert)) == peer


def test_basic_constraints_ca_false_is_accepted(make_cert):
    cert = make_cert(ca=False)
    assert peer_cert_from_pem(pem_of(cert)).fingerprint == fingerprint_of_der(der_of(cert))


def test_pem_exactly_at_limit_is_valid(identity):
    pem = identity.cert_pem()
    padded = pem + " " * (MAX_PEM - len(pem))
    assert len(padded) == MAX_PEM
    assert peer_cert_from_pem(padded).pem == pem


def test_pem_one_over_limit_is_rejected(identity):
    pem = identity.cert_pem()
    padded = pem + " " * (MAX_PEM + 1 - len(pem))
    assert len(padded) == MAX_PEM + 1
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(padded)


# --- PeerCert: chứng chỉ xấu (tự tạo bằng cryptography) ----------------------------------------


@pytest.mark.parametrize(
    "cn",
    [
        "foo",
        "teleport-",
        "teleport-" + "AB" * 16,
        "teleport-" + "a" * 31,
        "teleport-" + "a" * 33,
        "teleport-" + "g" * 32,
        "Teleport-" + "a" * 32,
        "teleport_" + "a" * 32,
        "a" * 32,
        "xteleport-" + "a" * 32,
        "teleport-" + "a" * 32 + "\n",
        "teleport-" + "０" * 10 + "a" * 22,  # 32 code point, có chữ số toàn chiều rộng
    ],
    ids=repr,
)
def test_wrong_common_name_rejected(make_cert, cn):
    cert = make_cert(cn=cn)
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem_of(cert))
    with pytest.raises(InvalidCertificate):
        peer_cert_from_der(der_of(cert))


def test_two_common_names_rejected(make_cert):
    cert = make_cert(cn="teleport-" + "a" * 32, extra_cn="teleport-" + "b" * 32)
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem_of(cert))


def test_rsa_key_rejected(make_cert, rsa_key):
    cert = make_cert(key=rsa_key)
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem_of(cert))
    with pytest.raises(InvalidCertificate):
        peer_cert_from_der(der_of(cert))


@pytest.mark.parametrize("hash_alg", [hashes.SHA256(), hashes.SHA384()], ids=["sha256", "sha384"])
def test_p384_key_rejected(make_cert, hash_alg):
    cert = make_cert(key=ec.generate_private_key(ec.SECP384R1()), hash_alg=hash_alg)
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem_of(cert))


@pytest.mark.parametrize(
    "hash_alg", [hashes.SHA384(), hashes.SHA512(), hashes.SHA224()], ids=["sha384", "sha512", "sha224"]
)
def test_p256_with_non_sha256_signature_rejected(make_cert, hash_alg):
    cert = make_cert(hash_alg=hash_alg)
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem_of(cert))


NETSCAPE_CERT_TYPE = x509.ObjectIdentifier("2.16.840.1.113730.1.1")


def key_usage(**flags) -> x509.KeyUsage:
    fields = dict.fromkeys(
        [
            "digital_signature",
            "content_commitment",
            "key_encipherment",
            "data_encipherment",
            "key_agreement",
            "key_cert_sign",
            "crl_sign",
            "encipher_only",
            "decipher_only",
        ],
        False,
    )
    fields.update(flags)
    return x509.KeyUsage(**fields)


@pytest.mark.parametrize(
    ("ext", "critical"),
    [
        (key_usage(key_cert_sign=True), True),
        (key_usage(key_cert_sign=True), False),
        (key_usage(digital_signature=True, key_cert_sign=True), True),
        (key_usage(crl_sign=True), True),
        (key_usage(digital_signature=True, key_agreement=True, crl_sign=True), False),
        (key_usage(key_cert_sign=True, crl_sign=True), True),
        # Netscape Cert Type (bit sslCA = 0x04): BIT STRING 03 02 02 04.
        (x509.UnrecognizedExtension(NETSCAPE_CERT_TYPE, b"\x03\x02\x02\x04"), False),
        # Kể cả khi chỉ khai sslClient (0x80): cấm cả extension, không cần biết bit nào.
        (x509.UnrecognizedExtension(NETSCAPE_CERT_TYPE, b"\x03\x02\x07\x80"), False),
    ],
    ids=[
        "ku-keyCertSign-critical",
        "ku-keyCertSign-noncritical",
        "ku-ds+keyCertSign",
        "ku-cRLSign",
        "ku-ds+ka+cRLSign",
        "ku-keyCertSign+cRLSign",
        "netscape-sslCA",
        "netscape-sslClient",
    ],
)
def test_ca_like_extensions_rejected(make_cert, ext, critical):
    cert = make_cert(extensions=[(ext, critical)])
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem_of(cert))
    with pytest.raises(InvalidCertificate):
        peer_cert_from_der(der_of(cert))


@pytest.mark.parametrize(
    "ku",
    [
        key_usage(digital_signature=True),
        key_usage(digital_signature=True, key_agreement=True),
        key_usage(digital_signature=True, key_agreement=True, content_commitment=True),
        key_usage(digital_signature=True, key_agreement=True, key_encipherment=True, data_encipherment=True),
    ],
    ids=["ds", "ds+ka", "ds+ka+nr", "ds+ka+ke+de"],
)
def test_key_usage_without_cert_or_crl_sign_is_accepted(make_cert, ku):
    cert = make_cert(extensions=[(ku, True)])
    peer = peer_cert_from_pem(pem_of(cert))
    assert peer.fingerprint == fingerprint_of_der(der_of(cert))
    assert peer_cert_from_der(der_of(cert)) == peer


def test_key_usage_with_basic_constraints_ca_false_is_accepted(make_cert):
    cert = make_cert(ca=False, extensions=[(key_usage(digital_signature=True, key_agreement=True), True)])
    assert peer_cert_from_pem(pem_of(cert)).pem == pem_of(cert)


def test_own_identity_cert_still_valid_after_extension_rules(identity):
    assert peer_cert_from_pem(identity.cert_pem()).fingerprint == identity.fingerprint


def test_ca_true_rejected(make_cert):
    cert = make_cert(ca=True)
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem_of(cert))
    with pytest.raises(InvalidCertificate):
        peer_cert_from_der(der_of(cert))


def test_signed_by_other_key_rejected(make_cert):
    cert = make_cert(signing_key=ec.generate_private_key(ec.SECP256R1()))
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem_of(cert))
    with pytest.raises(InvalidCertificate):
        peer_cert_from_der(der_of(cert))


def test_issuer_different_from_subject_rejected(make_cert):
    cert = make_cert(issuer_cn="teleport-" + "c" * 32)
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem_of(cert))


def test_two_concatenated_certs_rejected(identity, make_cert):
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(identity.cert_pem() + pem_of(make_cert()))
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(identity.cert_pem() * 2)


@pytest.mark.parametrize(
    "mangle",
    [
        lambda p: "rác\n" + p,
        lambda p: "junk\n" + p,
        lambda p: p + "junk",
        lambda p: p + "\n# comment\n",
        lambda p: "Subject: CN=teleport\n" + p,
        lambda p: p + "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n",
    ],
    ids=[
        "non-ascii-prefix",
        "ascii-prefix",
        "suffix",
        "comment-suffix",
        "openssl-text-prefix",
        "extra-block",
    ],
)
def test_garbage_outside_pem_block_rejected(identity, mangle):
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(mangle(identity.cert_pem()))


@pytest.mark.parametrize(
    "mangle",
    [
        lambda p: p + "é",
        lambda p: "\u3000" + p,  # khoảng trắng nhưng không ASCII
        lambda p: p + "\u00a0",
        lambda p: p.replace("\n", "\nđ", 2),
        lambda p: p.replace("CERTIFICATE", "CERTIFICATÉ", 1),
        lambda p: "\ufeff" + p,
        lambda p: p + "\ud800",
    ],
    ids=["e-acute", "ideographic-space", "nbsp", "inside-block", "in-header", "bom", "lone-surrogate"],
)
def test_non_ascii_rejected_as_invalid_certificate(identity, mangle):
    # Phải là InvalidCertificate, không để lọt UnicodeEncodeError.
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(mangle(identity.cert_pem()))


@pytest.mark.parametrize(
    "pem",
    [
        "",
        "   ",
        "rác",
        "-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----\n",
        "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n",
        "-----BEGIN CERTIFICATE-----\nMIIBkTCCATegAwIBAgIU\n",
        "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n",
    ],
    ids=repr,
)
def test_garbage_pem_rejected(pem):
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem)


def test_truncated_pem_rejected(identity):
    pem = identity.cert_pem()
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem[: len(pem) // 2])
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem.replace("-----END CERTIFICATE-----", ""))


def test_private_key_pem_rejected(identity):
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(identity.key_path.read_text(encoding="ascii"))


@pytest.mark.parametrize("der", [b"", b"\x00", b"\x30\x00", b"rac" * 100, bytes(range(256))], ids=repr)
def test_garbage_der_rejected(der):
    with pytest.raises(InvalidCertificate):
        peer_cert_from_der(der)


def test_truncated_der_rejected(identity):
    der = ssl.PEM_cert_to_DER_cert(identity.cert_pem())
    with pytest.raises(InvalidCertificate):
        peer_cert_from_der(der[:-1])
    with pytest.raises(InvalidCertificate):
        peer_cert_from_der(der + b"\x00")


def test_cert_whose_pem_exceeds_limit_rejected_from_pem_and_der(make_cert):
    # Cert hợp lệ mọi mặt nhưng PEM chuẩn hóa dài hơn 8192 ký tự.
    cert = make_cert(san_dns=[f"may-so-{i}.example" for i in range(600)])
    assert len(pem_of(cert)) > MAX_PEM
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem_of(cert))
    with pytest.raises(InvalidCertificate):
        peer_cert_from_der(der_of(cert))


def test_large_but_within_limit_cert_accepted(make_cert):
    cert = make_cert(san_dns=[f"h{i}.example" for i in range(300)])
    assert len(pem_of(cert)) <= MAX_PEM
    assert peer_cert_from_der(der_of(cert)).pem == pem_of(cert)


def test_invalid_x509_version_rejected_from_pem_and_der(identity):
    # Trường version của X.509 v3 mã hóa là [0] INTEGER 2. Đổi thành 5 (tức "v6"):
    # `cryptography` ném InvalidVersion (không phải ValueError), có bản ném ngay lúc load.
    der = x509.load_pem_x509_certificate(identity.cert_pem().encode()).public_bytes(
        serialization.Encoding.DER
    )
    v3_field = b"\xa0\x03\x02\x01\x02"
    assert der.count(v3_field) == 1
    bad_der = der.replace(v3_field, b"\xa0\x03\x02\x01\x05")
    b64 = base64.encodebytes(bad_der).decode("ascii")
    bad_pem = f"-----BEGIN CERTIFICATE-----\n{b64}-----END CERTIFICATE-----\n"
    with pytest.raises(InvalidCertificate):
        peer_cert_from_der(bad_der)
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(bad_pem)


# --- M1: mọi lỗi khi phân tích hay kiểm chứng chỉ đều là InvalidCertificate ---------------------
#
# protocol §5.1: chứng chỉ nhận được phải "phân tích được"; lỗi bất kỳ trong lúc phân tích hay kiểm
# là chứng chỉ không hợp lệ, không được lọt lên tầng trên như một lỗi lạ. Mẫu thật: SAN chứa
# x400Address/EDIPartyName làm `cryptography` ném UnsupportedGeneralNameType (kế thừa thẳng từ
# Exception). Mẫu mô phỏng: thay hàm load hoặc thuộc tính của chứng chỉ để ném một lớp lỗi lạ.


def _parse(source, form: str):
    """`peer_cert_from_pem` hoặc `peer_cert_from_der` trên chứng chỉ của `source` (Identity hoặc x509)."""
    pem = pem_of(source) if isinstance(source, x509.Certificate) else source.cert_pem()
    return peer_cert_from_pem(pem) if form == "pem" else peer_cert_from_der(ssl.PEM_cert_to_DER_cert(pem))


def _loader_name(form: str) -> str:
    return "load_pem_x509_certificate" if form == "pem" else "load_der_x509_certificate"


class _OddError(Exception):
    """Lớp lỗi lạ, không chung gốc với ValueError (giống UnsupportedGeneralNameType)."""


class _Stop(BaseException):
    """Không phải Exception (như KeyboardInterrupt, CancelledError)."""


class _BrokenCert:
    """Bọc một chứng chỉ thật; đọc thuộc tính `broken` thì ném `error`."""

    def __init__(self, cert: x509.Certificate, broken: str, error: BaseException) -> None:
        self._cert = cert
        self._broken = broken
        self._error = error

    def __getattr__(self, name: str):
        if name == self._broken:
            raise self._error
        value = getattr(self._cert, name)
        if name == "verify_directly_issued_by":
            # Hàm thật cần chứng chỉ thật làm issuer, không nhận lớp bọc.
            return lambda issuer: value(issuer._cert if isinstance(issuer, _BrokenCert) else issuer)
        return value


def _wrap_loader(monkeypatch, form: str, broken: str, error: BaseException) -> list[_BrokenCert]:
    """Thay hàm load của `cryptography` để mọi chứng chỉ trả về đều là `_BrokenCert`."""
    name = _loader_name(form)
    real = getattr(x509, name)
    made: list[_BrokenCert] = []

    def load(data, *args, **kwargs):
        made.append(_BrokenCert(real(data, *args, **kwargs), broken, error))
        return made[-1]

    monkeypatch.setattr(x509, name, load)
    return made


def test_m1_unsupported_general_name_is_unparseable_by_cryptography(make_cert, unsupported_name_ext):
    """Tiền đề của các test M1 bên dưới: chính `cryptography` không đọc được extension mẫu."""
    cert = make_cert(extensions=[(unsupported_name_ext, False)])
    try:
        _ = cert.extensions
    except Exception:
        return
    pytest.fail("cryptography đọc được extension mẫu: test M1 với mẫu này không còn ý nghĩa")


@pytest.mark.parametrize("critical", [False, True], ids=["non-critical", "critical"])
def test_m1_cert_with_unsupported_general_name_rejected_from_pem_and_der(
    make_cert, unsupported_name_ext, critical
):
    cert = make_cert(extensions=[(unsupported_name_ext, critical)])
    with pytest.raises(InvalidCertificate):
        peer_cert_from_pem(pem_of(cert))
    with pytest.raises(InvalidCertificate):
        peer_cert_from_der(der_of(cert))


def test_m1_own_cert_with_unsupported_general_name_is_identity_error(
    tmp_path, make_cert, unsupported_name_ext
):
    """`device.crt` của chính máy mang tên lạ: IdentityError (CLI in câu và thoát 1), không tạo lại."""
    key = ec.generate_private_key(ec.SECP256R1())
    cert = make_cert(key=key, extensions=[(unsupported_name_ext, False)])
    (tmp_path / CERT_FILE).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / KEY_FILE).write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(IdentityError, match=CERT_FILE):
        load_or_create_identity(tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.name != IDENTITY_LOCK} == before


@pytest.mark.parametrize("form", ["pem", "der"])
def test_m1_unexpected_error_while_loading_is_invalid_certificate(identity, monkeypatch, form):
    calls = []

    def broken(*args, **kwargs):
        calls.append(args)
        raise _OddError("lỗi lạ lúc load")

    monkeypatch.setattr(x509, _loader_name(form), broken)
    with pytest.raises(InvalidCertificate) as exc:
        _parse(identity, form)
    assert calls, "hàm load bị thay chưa được gọi: phép thử vô nghĩa"
    assert isinstance(exc.value.__cause__, _OddError)


# Thuộc tính cần đọc để kiểm đủ các điều kiện ở protocol §5.1 (dấu hiệu CA, loại khóa, CN, thuật
# toán chữ ký, chữ ký tự ký) và để dựng PEM/fingerprint đã chuẩn hóa.
CHECKED_ATTRIBUTES = [
    "extensions",
    "public_key",
    "subject",
    "signature_algorithm_oid",
    "verify_directly_issued_by",
    "public_bytes",
]


@pytest.mark.parametrize("form", ["pem", "der"])
@pytest.mark.parametrize("attribute", CHECKED_ATTRIBUTES)
def test_m1_unexpected_error_while_checking_is_invalid_certificate(identity, monkeypatch, form, attribute):
    made = _wrap_loader(monkeypatch, form, attribute, _OddError(f"lỗi lạ khi đọc {attribute}"))
    with pytest.raises(InvalidCertificate) as exc:
        _parse(identity, form)
    assert made, "hàm load bị thay chưa được gọi: phép thử vô nghĩa"
    assert isinstance(exc.value.__cause__, _OddError)


@pytest.mark.parametrize("form", ["pem", "der"])
@pytest.mark.parametrize("stage", ["load", "extensions"])
def test_m1_base_exception_is_not_turned_into_invalid_certificate(identity, monkeypatch, form, stage):
    """Chỉ lỗi (Exception) mới thành InvalidCertificate; Ctrl+C hay hủy task phải bay ra nguyên vẹn."""
    if stage == "load":

        def broken(*args, **kwargs):
            raise _Stop

        monkeypatch.setattr(x509, _loader_name(form), broken)
    else:
        _wrap_loader(monkeypatch, form, "extensions", _Stop())
    with pytest.raises(_Stop):
        _parse(identity, form)


def _der_tlv(tag: int, content: bytes) -> bytes:
    length = len(content)
    if length < 0x80:
        return bytes([tag, length]) + content
    size = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(size)]) + size + content


# GeneralName bất kỳ: tag ngữ cảnh [0]..[8], dạng nguyên thủy hoặc cấu trúc, nội dung ngẫu nhiên.
_general_names = st.builds(
    lambda number, constructed, content: _der_tlv((0xA0 if constructed else 0x80) | number, content),
    st.integers(0, 8),
    st.booleans(),
    st.binary(max_size=40),
)
_general_name_lists = st.lists(_general_names, min_size=1, max_size=4).map(
    lambda names: _der_tlv(0x30, b"".join(names))
)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    oid=st.sampled_from([ExtensionOID.SUBJECT_ALTERNATIVE_NAME, ExtensionOID.ISSUER_ALTERNATIVE_NAME]),
    value=_general_name_lists,
    critical=st.booleans(),
)
def test_m1_fuzz_general_names_only_raise_invalid_certificate(make_cert, oid, value, critical):
    """SAN/IAN có GeneralName bất kỳ: hoặc là chứng chỉ hợp lệ, hoặc InvalidCertificate, không gì khác."""
    cert = make_cert(key=_fuzz_key(), extensions=[(x509.UnrecognizedExtension(oid, value), critical)])
    for form in ("pem", "der"):
        try:
            peer = _parse(cert, form)
        except InvalidCertificate:
            continue
        assert peer.fingerprint == fingerprint_of_der(der_of(cert))


@functools.cache
def _fuzz_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


# --- Fuzz --------------------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=300) | st.binary(max_size=300).map(lambda b: b.decode("latin-1")))
def test_fuzz_peer_cert_from_pem_only_raises_invalid_certificate(text):
    try:
        peer = peer_cert_from_pem(text)
    except InvalidCertificate:
        return
    assert isinstance(peer, PeerCert)


@settings(max_examples=200, deadline=None)
@given(st.binary(max_size=600))
def test_fuzz_peer_cert_from_der_only_raises_invalid_certificate(der):
    try:
        peer = peer_cert_from_der(der)
    except InvalidCertificate:
        return
    assert isinstance(peer, PeerCert)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_fuzz_mutated_valid_pem_only_raises_invalid_certificate(identity, data):
    pem = identity.cert_pem()
    i = data.draw(st.integers(0, len(pem) - 1))
    ch = data.draw(st.characters())
    mutated = pem[:i] + ch + pem[i + 1 :]
    try:
        peer = peer_cert_from_pem(mutated)
    except InvalidCertificate:
        return
    assert isinstance(peer, PeerCert)
    assert peer.pem.isascii()
