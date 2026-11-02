"""Bên nhận: `check_offer`, `mtime_ms`, luồng `offer` và bảng protocol §6.3 cột “Nhận”.

Spec P2-4 mục 2.6, 3.2, 3.5, 3.12; AC-2, AC-3, AC-4. Viết từ spec và docs/protocol.md (§3.3, §4.1,
§6.3), không từ code. Engine được lái qua API công khai bằng bộ lái `tx.Recv` (tests/core/conftest.py).
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from teleport.core.blocks import BLOCK_SIZE, MAX_FILE_SIZE
from teleport.core.filenames import dedupe_offer_names
from teleport.core.messages import (
    MAX_SAFE_INTEGER,
    Accept,
    Cancel,
    Complete,
    FileEntry,
    Offer,
    Reject,
    Resume,
    Verified,
)
from teleport.core.transfer import (
    RECONNECT_GRACE,
    AskUser,
    CheckSpace,
    CreateTemp,
    DiskOp,
    FailureDetail,
    Outcome,
    RemoveTemp,
    SyncPart,
    TombstonesChanged,
    TransferEngine,
    TransferStatus,
    check_offer,
    mtime_ms,
)

FAT32 = 2**32 - 1
HYPO = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def offer_of(*sizes: int, T: str = "1" * 32) -> Offer:
    files = tuple(FileEntry(name=f"f{i}", size=s, mtime=0) for i, s in enumerate(sizes))
    return Offer(transfer_id=T, block_size=BLOCK_SIZE, files=files)


# ---- AC-2: check_offer / mtime_ms ---------------------------------------------------------------


def test_check_offer_reports_first_file_too_large():
    o = offer_of(10, 2**32, 2**33)
    assert check_offer(o, free_bytes=5, max_file_size=FAT32) == Reject(
        transfer_id=o.transfer_id, reason="file_too_large", file_index=1, max_size=FAT32
    )


def test_check_offer_file_too_large_is_checked_before_no_space():
    o = offer_of(2**33)
    rej = check_offer(o, free_bytes=0, max_file_size=FAT32)
    assert rej is not None and rej.reason == "file_too_large"


def test_check_offer_file_exactly_at_limit_fits():
    assert check_offer(offer_of(FAT32, 1), free_bytes=None, max_file_size=FAT32) is None


def test_check_offer_no_space_reports_needed_and_available():
    o = offer_of(3, 4)
    assert check_offer(o, free_bytes=6, max_file_size=None) == Reject(
        transfer_id=o.transfer_id, reason="no_space", needed=7, available=6
    )


def test_check_offer_exactly_enough_space_fits():
    assert check_offer(offer_of(3, 4), free_bytes=7, max_file_size=None) is None


def test_check_offer_unknown_limits_accept_anything():
    assert check_offer(offer_of(MAX_FILE_SIZE, MAX_FILE_SIZE), free_bytes=None, max_file_size=None) is None


def test_check_offer_empty_files_fit_on_full_disk():
    assert check_offer(offer_of(0, 0), free_bytes=0, max_file_size=0) is None


@HYPO
@given(
    sizes=st.lists(st.integers(0, MAX_FILE_SIZE), min_size=1, max_size=6),
    free=st.none() | st.integers(0, 2**60),
    mx=st.none() | st.integers(0, 2**43),
)
def test_check_offer_matches_definition(sizes, free, mx):
    o = offer_of(*sizes)
    expected = None
    if mx is not None and any(s > mx for s in sizes):
        first = next(i for i, s in enumerate(sizes) if s > mx)
        expected = Reject(transfer_id=o.transfer_id, reason="file_too_large", file_index=first, max_size=mx)
    elif free is not None and sum(sizes) > free:
        expected = Reject(
            transfer_id=o.transfer_id,
            reason="no_space",
            needed=sum(sizes),
            available=min(free, MAX_SAFE_INTEGER),
        )
    assert check_offer(o, free_bytes=free, max_file_size=mx) == expected


@pytest.mark.parametrize(
    "kw",
    [
        {"free_bytes": -1, "max_file_size": None},
        {"free_bytes": True, "max_file_size": None},
        {"free_bytes": 1.5, "max_file_size": None},
        {"free_bytes": "10", "max_file_size": None},
        {"free_bytes": None, "max_file_size": -1},
        {"free_bytes": None, "max_file_size": False},
        {"free_bytes": None, "max_file_size": 2.0},
    ],
)
def test_check_offer_rejects_bad_limits(kw):
    with pytest.raises(ValueError):
        check_offer(offer_of(1), **kw)


@pytest.mark.parametrize("bad", [None, {"type": "offer"}, Accept(transfer_id="1" * 32)])
def test_check_offer_rejects_non_offer(bad):
    with pytest.raises(TypeError):
        check_offer(bad, free_bytes=None, max_file_size=None)


@pytest.mark.parametrize(
    ("ns", "ms"),
    [
        (0, 0),
        (999_999, 0),
        (1_000_000, 1),
        (1_700_000_000_123_456_789, 1_700_000_000_123),
        (-1, 0),
        (-5_000_000_000_000, 0),
        (MAX_SAFE_INTEGER * 10**6, MAX_SAFE_INTEGER),
        (MAX_SAFE_INTEGER * 10**6 + 999_999, MAX_SAFE_INTEGER),
        ((MAX_SAFE_INTEGER + 1) * 10**6, MAX_SAFE_INTEGER),
        (10**40, MAX_SAFE_INTEGER),
    ],
)
def test_mtime_ms_converts_and_clamps(ns, ms):
    assert mtime_ms(ns) == ms


@pytest.mark.parametrize("bad", [True, False, 1.5, "1", None])
def test_mtime_ms_rejects_non_int(bad):
    with pytest.raises(TypeError):
        mtime_ms(bad)


# ---- AC-3: luồng offer bên nhận -----------------------------------------------------------------


def test_new_offer_asks_for_space_check(tx):
    r = tx.Recv(tx.entries(2, 3))
    r.up()
    acts = r.send_offer()
    cs = tx.one(acts, CheckSpace)
    assert (cs.device_id, cs.transfer_id, cs.total_size) == (tx.PEER, r.T, tx.size_of(2) + tx.size_of(3))
    assert tx.sent(acts) == []
    assert tx.statuses(acts, r.key) == [TransferStatus.WAITING]
    assert r.e.info(r.key).status == TransferStatus.WAITING


def test_file_too_large_rejects_remembers_and_reports(tx):
    r = tx.Recv(tx.entries(1, 3, 4))
    r.up()
    r.send_offer()
    mx = tx.size_of(2)
    acts = r.call("space_checked", tx.PEER, r.T, tx.FREE, mx)
    rej = Reject(transfer_id=r.T, reason="file_too_large", file_index=1, max_size=mx)
    assert tx.sent(acts) == [rej]
    assert not tx.of(acts, AskUser)
    end = tx.one(tx.ended(acts), object)
    assert end.key == r.key
    assert end.outcome == Outcome.REJECTED
    assert end.reason == "file_too_large"
    assert end.by_peer is False
    assert end.reject == rej
    assert end.file_index == 1
    assert end.detail is None
    assert r.e.info(r.key) is None
    # `reject` được nhớ: `offer` gửi lại nhận lại đúng `reject` đó, không hỏi lại dung lượng.
    acts = r.send_offer()
    assert tx.sent(acts) == [rej]
    assert not tx.of(acts, CheckSpace)
    assert not tx.ended(acts)


def test_no_space_rejects_with_needed_and_available(tx):
    r = tx.Recv(tx.entries(2, 1))
    r.up()
    r.send_offer()
    acts = r.call("space_checked", tx.PEER, r.T, 100, None)
    rej = Reject(transfer_id=r.T, reason="no_space", needed=tx.size_of(2) + tx.size_of(1), available=100)
    assert tx.sent(acts) == [rej]
    end = tx.one(tx.ended(acts), object)
    assert (end.outcome, end.reason, end.by_peer, end.reject) == (Outcome.REJECTED, "no_space", False, rej)
    assert tx.sent(r.send_offer()) == [rej]


def test_enough_space_asks_user_with_sanitized_names(tx):
    raw = ["../../etc/passwd", "CON", "a.txt", "A.TXT", "C:\\Users\\x\\b.doc", ""]
    r = tx.Recv(tx.entries(0, 0, 1, 0, 0, 0, names=raw))
    acts = r.to_asking()
    ask = tx.one(acts, AskUser)
    assert (ask.device_id, ask.transfer_id) == (tx.PEER, r.T)
    assert ask.offer == r.offer
    assert ask.names == tuple(dedupe_offer_names(raw))
    assert tx.sent(acts) == []
    assert r.e.info(r.key).names == tuple(dedupe_offer_names(raw))


def test_unknown_space_asks_user(tx):
    r = tx.Recv(tx.entries(3))
    r.up()
    r.send_offer()
    acts = r.call("space_checked", tx.PEER, r.T, None, None)
    assert tx.one(acts, AskUser).transfer_id == r.T
    assert tx.sent(acts) == []


def test_not_receiving_rejects_without_remembering(tx):
    r = tx.Recv(tx.entries(1), receiving=False)
    r.up()
    acts = r.send_offer()
    assert tx.sent(acts) == [Reject(transfer_id=r.T, reason="not_receiving")]
    assert tx.events(acts) == []
    assert r.e.info(r.key) is None
    assert r.e.transfers() == ()
    # Chưa bật nhận: `offer` gửi lại vẫn bị từ chối như `offer` mới.
    assert tx.sent(r.send_offer()) == [Reject(transfer_id=r.T, reason="not_receiving")]
    # Bật nhận: `offer` gửi lại được xét như `offer` mới (không có `reject` nào được nhớ).
    r.e.receiving = True
    acts = r.send_offer()
    assert tx.one(acts, CheckSpace).transfer_id == r.T
    assert tx.sent(acts) == []


def test_receiving_flag_only_applies_to_new_offers(tx):
    r = tx.Recv(tx.entries(1))
    r.up()
    r.send_offer()  # CHECKING
    r.e.receiving = False
    assert r.e.receiving is False
    acts = r.call("space_checked", tx.PEER, r.T, tx.FREE, None)
    assert tx.one(acts, AskUser).transfer_id == r.T
    assert tx.sent(r.send_offer()) == []


@pytest.mark.parametrize("bad", [1, 0, None, "yes"])
def test_receiving_setter_rejects_non_bool(tx, bad):
    e = TransferEngine(tx.ME, receiving=True)
    with pytest.raises(TypeError):
        e.receiving = bad
    assert e.receiving is True


@pytest.mark.parametrize("first_state", ["asking", "running"])
def test_second_offer_from_same_device_is_queued_silently(tx, first_state):
    r1 = tx.Recv(tx.entries(1))
    if first_state == "asking":
        r1.to_asking()
    else:
        r1.accept()
    r2 = tx.Recv(tx.entries(1), T=tx.T2, like=r1)
    acts = r2.send_offer()
    assert tx.sent(acts) == []
    assert not tx.of(acts, (CheckSpace, AskUser))
    assert tx.statuses(acts, r2.key) == [TransferStatus.QUEUED]
    assert r1.e.info(r2.key).status == TransferStatus.QUEUED


def test_ninth_unanswered_offer_is_busy_and_not_remembered(tx):
    first = tx.Recv(tx.entries(1), T=tx.tid(1))
    first.up()
    ds = [first] + [tx.Recv(tx.entries(1), T=tx.tid(k), like=first) for k in range(2, 10)]
    for d in ds[:8]:
        assert tx.sent(d.send_offer()) == []
    acts = ds[8].send_offer()
    assert tx.sent(acts) == [Reject(transfer_id=tx.tid(9), reason="busy")]
    assert tx.events(acts) == []
    assert first.e.info(ds[8].key) is None
    # Một chỗ được giải phóng: `offer` thứ 9 gửi lại được xét như `offer` mới (không nhớ `busy`).
    first.call("space_checked", tx.PEER, first.T, 0, None)  # đầu hàng bị no_space
    acts = ds[8].send_offer()
    assert tx.sent(acts) == []
    assert tx.statuses(acts, ds[8].key) == [TransferStatus.QUEUED]


def test_running_transfer_does_not_count_toward_offer_queue(tx):
    first = tx.Recv(tx.entries(1), T=tx.tid(1))
    first.accept()
    ds = [tx.Recv(tx.entries(1), T=tx.tid(k), like=first) for k in range(2, 11)]
    for d in ds[:8]:
        assert tx.sent(d.send_offer()) == []
    assert tx.sent(ds[8].send_offer()) == [Reject(transfer_id=tx.tid(10), reason="busy")]


def test_resent_queued_offer_is_ignored_even_when_queue_full(tx):
    first = tx.Recv(tx.entries(1), T=tx.tid(1))
    first.up()
    ds = [first] + [tx.Recv(tx.entries(1), T=tx.tid(k), like=first) for k in range(2, 9)]
    for d in ds:
        d.send_offer()
    acts = ds[5].send_offer()
    assert tx.sent(acts) == []
    assert tx.events(acts) == []


@pytest.mark.parametrize("how", ["done", "rejected", "peer_cancel", "user_cancel", "disk_error"])
def test_oldest_queued_offer_is_checked_when_previous_ends(tx, how):
    r1 = tx.Recv(tx.entries(1))
    if how == "rejected":
        r1.to_asking()
    else:
        r1.accept()
    r2 = tx.Recv(tx.entries(2), T=tx.T2, like=r1)
    r3 = tx.Recv(tx.entries(1), T=tx.T3, like=r1)
    r2.send_offer()
    r3.send_offer()
    if how == "done":
        acts = r1.finish_all()
    elif how == "rejected":
        acts = r1.call("decide", tx.PEER, r1.T, False)
    elif how == "peer_cancel":
        acts = r1.msg(Cancel(transfer_id=r1.T, reason="user"))
    elif how == "user_cancel":
        acts = r1.call("cancel", r1.key)
    else:
        acts = r1.call("storage_failed", tx.PEER, r1.T, DiskOp.WRITE)
    cs = tx.one(acts, CheckSpace)
    assert (cs.transfer_id, cs.total_size) == (tx.T2, tx.size_of(2))
    assert tx.statuses(acts, r2.key) == [TransferStatus.WAITING]
    assert r1.e.info(r3.key).status == TransferStatus.QUEUED


def test_expiry_ends_queued_offers_too(tx):
    r1 = tx.Recv(tx.entries(1))
    r1.accept()
    r2 = tx.Recv(tx.entries(1), T=tx.T2, like=r1)
    r2.send_offer()
    r1.lost(now=100.0)
    acts = r1.tick(now=100.0 + RECONNECT_GRACE)
    ends = {e.key: e for e in tx.ended(acts)}
    assert set(ends) == {r1.key, r2.key}
    assert all(e.reason == "expired" and e.outcome == Outcome.CANCELLED for e in ends.values())
    assert r1.e.transfers() == ()


def test_promised_bytes_makes_second_device_run_out_of_space(tx):
    x = tx.size_of(3)
    ra = tx.Recv(tx.entries(3))
    rc = tx.Recv(tx.entries(3), T=tx.T2, peer=tx.OTHER, like=ra, cid=2)
    ra.up()
    rc.up()
    ra.send_offer()
    rc.send_offer()
    assert ra.e.promised_bytes() == 0  # CHECKING không được tính
    acts = ra.call("space_checked", tx.PEER, ra.T, x + x // 2, None)
    assert tx.one(acts, AskUser).transfer_id == ra.T
    assert ra.e.promised_bytes() == x  # ASKING được tính
    acts = rc.call("space_checked", tx.OTHER, rc.T, x + x // 2, None)
    rej = Reject(transfer_id=rc.T, reason="no_space", needed=x, available=x // 2)
    assert tx.sent(acts) == [rej]
    assert tx.one(tx.ended(acts), object).reject == rej


def test_promised_bytes_tracks_running_transfer_with_short_last_block(tx):
    files = (
        FileEntry(name="a", size=3 * BLOCK_SIZE, mtime=1),
        FileEntry(name="b", size=BLOCK_SIZE + 100, mtime=2),
    )
    r = tx.Recv(files)
    r.to_asking()
    total = files[0].size + files[1].size
    assert r.e.promised_bytes() == total
    r.call("decide", tx.PEER, r.T, True)
    assert r.e.promised_bytes() == total
    r.created()  # P3-2: `resume` đầu tiên chỉ sau `temp_created`
    assert r.e.promised_bytes() == total
    did, _ = r.open()
    acts = r.feed(did, 0, [0, 1])
    assert r.e.promised_bytes() == total - 2 * BLOCK_SIZE  # đã ghi, chưa fsync: vẫn tính là đã ghi
    r.sync_all(acts)
    assert r.e.promised_bytes() == total - 2 * BLOCK_SIZE
    r.finish_file(0)
    assert r.e.promised_bytes() == files[1].size
    did, _ = r.open()
    r.feed(did, 1, [0])
    assert r.e.promised_bytes() == 100
    r.feed(did, 1, [1])
    assert r.e.promised_bytes() == 0


def test_queued_offer_is_not_promised(tx):
    r1 = tx.Recv(tx.entries(2))
    r1.to_asking()
    r2 = tx.Recv(tx.entries(5), T=tx.T2, like=r1)
    r2.send_offer()
    assert r1.e.promised_bytes() == tx.size_of(2)


# ---- AC-4: bảng §6.3 cột “Nhận” -----------------------------------------------------------------


def tombstoned(tx, reason_via: str = "user"):
    """Lượt nhận đang chạy bị người dùng hủy → bia mộ (RECEIVE, T, "user")."""
    r = tx.Recv(tx.entries(2))
    r.accept()
    acts = r.call("cancel", r.key)
    assert Cancel(transfer_id=r.T, reason="user") in tx.sent(acts)
    return r


def test_rule1_offer_of_tombstoned_transfer_gets_same_cancel(tx):
    r = tombstoned(tx)
    acts = r.send_offer()
    assert tx.sent(acts) == [Cancel(transfer_id=r.T, reason="user")]
    assert tx.events(acts) == []
    assert not tx.of(acts, (CheckSpace, CreateTemp))


def test_rule1_complete_of_tombstoned_transfer_gets_same_cancel(tx):
    r = tombstoned(tx)
    acts = r.complete(0)
    assert tx.sent(acts) == [Cancel(transfer_id=r.T, reason="user")]


def _changed_manifests(tx):
    base = tx.entries(2, 1)
    return {
        "mtime": (base[0], FileEntry(name=base[1].name, size=base[1].size, mtime=base[1].mtime + 1)),
        "name": (FileEntry(name="khac.bin", size=base[0].size, mtime=base[0].mtime), base[1]),
        "size": (FileEntry(name=base[0].name, size=base[0].size - 1, mtime=base[0].mtime), base[1]),
        "extra_file": (*base, FileEntry(name="x", size=0, mtime=0)),
        "fewer_files": (base[0],),
    }


@pytest.mark.parametrize("change", ["mtime", "name", "size", "extra_file", "fewer_files"])
@pytest.mark.parametrize("state", ["checking", "asking", "queued"])
def test_rule2_changed_manifest_of_waiting_offer_cancels(tx, state, change):
    head = tx.Recv(tx.entries(1), T=tx.T3)
    head.up()
    if state == "queued":
        head.send_offer()
    r = tx.Recv(tx.entries(2, 1), like=head)
    if state == "asking":
        r.to_asking(up=False)
    else:
        r.send_offer()
    other = Offer(transfer_id=r.T, block_size=BLOCK_SIZE, files=_changed_manifests(tx)[change])
    acts = r.send_offer(other)
    assert tx.sent(acts) == [Cancel(transfer_id=r.T, reason="error")]
    end = tx.one(tx.ended(acts), object)
    assert (end.key, end.outcome, end.reason, end.by_peer, end.detail) == (
        r.key,
        Outcome.CANCELLED,
        "error",
        False,
        FailureDetail.PROTOCOL,
    )
    assert not tx.of(acts, RemoveTemp)
    assert r.e.info(r.key) is None
    # Bia mộ: `offer` gửi lại (kể cả đúng manifest đầu) chỉ nhận lại `cancel{error}`.
    assert tx.sent(r.send_offer()) == [Cancel(transfer_id=r.T, reason="error")]
    # Lời hỏi đã bỏ: người dùng trả lời muộn không tạo gì.
    assert r.call("decide", tx.PEER, r.T, True) == []


@pytest.mark.parametrize("change", ["mtime", "name", "size", "extra_file", "fewer_files"])
def test_rule2_changed_manifest_of_running_transfer_cancels_and_removes_temp(tx, change):
    r = tx.Recv(tx.entries(2, 1))
    r.accept()
    other = Offer(transfer_id=r.T, block_size=BLOCK_SIZE, files=_changed_manifests(tx)[change])
    acts = r.send_offer(other)
    assert tx.sent(acts) == [Cancel(transfer_id=r.T, reason="error")]
    end = tx.one(tx.ended(acts), object)
    assert (end.outcome, end.reason, end.detail) == (Outcome.CANCELLED, "error", FailureDetail.PROTOCOL)
    rm = tx.one(acts, RemoveTemp)
    assert (rm.device_id, rm.transfer_id) == (tx.PEER, r.T)


def test_rule3_resends_remembered_user_reject(tx):
    r = tx.Recv(tx.entries(1))
    r.to_asking()
    acts = r.call("decide", tx.PEER, r.T, False)
    rej = Reject(transfer_id=r.T, reason="user")
    assert tx.sent(acts) == [rej]
    end = tx.one(tx.ended(acts), object)
    assert (end.outcome, end.reason, end.by_peer, end.reject) == (Outcome.REJECTED, "user", False, rej)
    acts = r.send_offer()
    assert tx.sent(acts) == [rej]
    assert not tx.of(acts, (CheckSpace, AskUser))


def test_rule3_running_with_resume_on_current_connection_resends_accept_only(tx):
    r = tx.Recv(tx.entries(3))
    r.accept()
    assert len(r.resumes()) == 1
    acts = r.send_offer()
    assert tx.sent(acts) == [Accept(transfer_id=r.T)]


def test_rule3_running_with_resume_pending_fsync_resends_accept_only(tx):
    r = tx.Recv(tx.entries(3))
    r.accept()
    did, _ = r.open()
    r.feed(did, 0, [0, 1])  # đã ghi, chưa fsync
    acts = r.lost()
    sp = tx.one(acts, SyncPart)  # đẩy lô sớm khi mất kết nối điều khiển
    acts = r.up(cid=2)
    assert tx.sent(acts) == [Accept(transfer_id=r.T)]  # `resume` chờ `synced`
    acts = r.send_offer()
    assert tx.sent(acts) == [Accept(transfer_id=r.T)]
    acts = r.sync([sp])
    res = tx.sent(acts, Resume)
    assert len(res) == 1
    assert res[0].seq == 1
    assert tx.bits_on(res[0].bitfield, 3) == {0, 1}


def test_rule3_done_transfer_resends_accept_only(tx):
    r = tx.Recv(tx.entries(1))
    r.accept()
    acts = r.finish_all()
    assert tx.one(tx.ended(acts), object).outcome == Outcome.DONE
    acts = r.send_offer()
    assert tx.sent(acts) == [Accept(transfer_id=r.T)]
    assert not tx.of(acts, (CheckSpace, AskUser, CreateTemp))
    assert tx.events(acts) == []


@pytest.mark.parametrize("state", ["checking", "asking", "queued"])
def test_rule4_resent_waiting_offer_is_ignored(tx, state):
    head = tx.Recv(tx.entries(1), T=tx.T3)
    head.up()
    if state == "queued":
        head.send_offer()
    r = tx.Recv(tx.entries(2), like=head)
    if state == "asking":
        r.to_asking(up=False)
    else:
        r.send_offer()
    acts = r.send_offer()
    assert tx.sent(acts) == []
    assert not tx.of(acts, (CheckSpace, AskUser))
    assert tx.events(acts) == []


@pytest.mark.parametrize("state", ["checking", "asking", "queued"])
def test_rule5_complete_of_unaccepted_offer_cancels(tx, state):
    head = tx.Recv(tx.entries(1), T=tx.T3)
    head.up()
    if state == "queued":
        head.to_asking(up=False)
    r = tx.Recv(tx.entries(2), like=head)
    if state == "asking":
        r.to_asking(up=False)
    else:
        r.send_offer()
    acts = r.complete(0)
    assert tx.sent(acts) == [Cancel(transfer_id=r.T, reason="error")]
    end = tx.one(tx.ended(acts), object)
    assert (end.key, end.outcome, end.detail) == (r.key, Outcome.CANCELLED, FailureDetail.PROTOCOL)
    assert r.e.info(r.key) is None
    assert r.call("decide", tx.PEER, r.T, True) == []
    assert r.call("space_checked", tx.PEER, r.T, tx.FREE, None) == []
    if state == "queued":
        # Lượt đầu hàng kết thúc: lượt đã hủy không được xét lại.
        acts = head.call("decide", tx.PEER, head.T, False)
        assert not [a for a in tx.of(acts, CheckSpace) if a.transfer_id == r.T]


def test_rule6_complete_of_done_transfer_resends_verified(tx):
    r = tx.Recv(tx.entries(1, 2))
    r.accept()
    r.finish_all()
    assert tx.sent(r.complete(0)) == [Verified(transfer_id=r.T, file_index=0)]
    assert tx.sent(r.complete(1)) == [Verified(transfer_id=r.T, file_index=1)]


def test_rule6_complete_beyond_files_of_done_transfer_cancels(tx):
    """Protocol §6.3, “Lỗi khi so với `offer`”: `file_index` không nhỏ hơn số file → `cancel{error}`
    và bia mộ đè lên mục DONE; không có sự kiện nào (lượt đã kết thúc)."""
    r = tx.Recv(tx.entries(1, 2))
    r.accept()
    r.finish_all()
    acts = r.msg(Complete(transfer_id=r.T, file_index=5, merkle_root="ab" * 32))
    assert tx.sent(acts) == [Cancel(transfer_id=r.T, reason="error")]
    assert tx.events(acts) == []
    assert tx.of(acts, TombstonesChanged)  # bia mộ được ghi xuống đĩa
    assert tx.sent(r.complete(0)) == [Cancel(transfer_id=r.T, reason="error")]


def test_rule6_complete_of_earlier_file_of_running_transfer_resends_verified(tx):
    r = tx.Recv(tx.entries(1, 2))
    r.accept()
    r.finish_file(0)
    acts = r.complete(0)
    assert tx.sent(acts) == [Verified(transfer_id=r.T, file_index=0)]
    assert tx.ended(acts) == []


def test_rule7_complete_of_unknown_transfer_gets_unknown_transfer(tx):
    r = tx.Recv(tx.entries(1))
    r.up()
    acts = r.complete(0, root=b"\x11" * 32)
    assert tx.sent(acts) == [Cancel(transfer_id=r.T, reason="unknown_transfer")]
    assert tx.events(acts) == []


def test_rule7_complete_from_other_device_for_same_id_is_unknown(tx):
    r = tx.Recv(tx.entries(1))
    r.accept()
    before = r.e.info(r.key)
    c = tx.Recv(tx.entries(1), peer=tx.OTHER, like=r, cid=7)
    c.up()
    acts = c.complete(0, root=r.root(0))
    assert tx.sent(acts) == [Cancel(transfer_id=r.T, reason="unknown_transfer")]
    assert all(a.device_id == tx.OTHER for a in tx.of(acts, tx.tr.SendMessage))
    assert r.e.info(r.key) == before


def test_rule8_offer_reusing_id_of_running_send_is_cancelled(tx):
    s = tx.Send(tx.entries(1))
    s.start(accept=False)
    r = tx.Recv(tx.entries(2), like=s)
    acts = r.send_offer()
    assert tx.sent(acts) == [Cancel(transfer_id=r.T, reason="error")]
    assert tx.events(acts) == []
    assert not tx.of(acts, CheckSpace)
    assert s.e.info(s.key) is not None
    assert s.e.info(r.key) is None
    # Bia mộ (RECEIVE, T, "error").
    assert tx.sent(r.send_offer()) == [Cancel(transfer_id=r.T, reason="error")]


def test_rule8_offer_reusing_id_of_tombstoned_send_is_cancelled(tx):
    s = tx.Send(tx.entries(1))
    s.start(accept=False)
    s.call("cancel", s.key)  # bia mộ (SEND, T, "user")
    r = tx.Recv(tx.entries(2), like=s)
    acts = r.send_offer()
    assert tx.sent(acts) == [Cancel(transfer_id=r.T, reason="error")]
    assert tx.events(acts) == []


def test_rule_order_tombstone_beats_changed_manifest(tx):
    r = tombstoned(tx)
    other = Offer(transfer_id=r.T, block_size=BLOCK_SIZE, files=tx.entries(7))
    assert tx.sent(r.send_offer(other)) == [Cancel(transfer_id=r.T, reason="user")]
    # Bia mộ không bị ghi đè thành "error".
    assert tx.sent(r.send_offer()) == [Cancel(transfer_id=r.T, reason="user")]


def test_rule_order_remembered_reject_has_no_manifest_to_compare(tx):
    r = tx.Recv(tx.entries(1))
    r.to_asking()
    r.call("decide", tx.PEER, r.T, False)
    other = Offer(transfer_id=r.T, block_size=BLOCK_SIZE, files=tx.entries(4, 4))
    assert tx.sent(r.send_offer(other)) == [Reject(transfer_id=r.T, reason="user")]


def test_rule_order_changed_manifest_beats_done_answer(tx):
    r = tx.Recv(tx.entries(1))
    r.accept()
    r.finish_all()
    other = Offer(transfer_id=r.T, block_size=BLOCK_SIZE, files=tx.entries(2))
    acts = r.send_offer(other)
    assert tx.sent(acts) == [Cancel(transfer_id=r.T, reason="error")]


def test_rule_order_tombstone_beats_unknown_for_complete(tx):
    r = tombstoned(tx)
    acts = r.msg(Complete(transfer_id=r.T, file_index=1, merkle_root="cd" * 32))
    assert tx.sent(acts) == [Cancel(transfer_id=r.T, reason="user")]


def test_rule_order_reused_send_id_beats_not_receiving(tx):
    s = tx.Send(tx.entries(1))
    s.start(accept=False)
    s.e.receiving = False
    r = tx.Recv(tx.entries(1), like=s)
    assert tx.sent(r.send_offer()) == [Cancel(transfer_id=r.T, reason="error")]


def test_rule_order_not_receiving_beats_busy(tx):
    first = tx.Recv(tx.entries(1), T=tx.tid(1))
    first.up()
    ds = [first] + [tx.Recv(tx.entries(1), T=tx.tid(k), like=first) for k in range(2, 10)]
    for d in ds[:8]:
        d.send_offer()
    first.e.receiving = False
    assert tx.sent(ds[8].send_offer()) == [Reject(transfer_id=tx.tid(9), reason="not_receiving")]
