"""Bên gửi theo bảng §6.3, `seq` và kết nối dữ liệu (§4.1), lịch thử lại và hạn chót.

Spec P2-4 mục 3.4, 3.6, 3.14; AC-5, AC-7, AC-8, AC-23 và các ca biên `seq` = 2⁵³−1, `resume` của
hai lượt xen nhau, kết nối chờ có hạn đúng bằng `now`. Viết từ spec và docs/protocol.md §4.1, §6.2,
§6.3, không từ code. Thời gian là thời gian ảo.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import teleport.core.keepalive as keepalive
import teleport.core.transfer as transfer
from teleport.core.bitfield import Bitfield
from teleport.core.messages import (
    MAX_SAFE_INTEGER,
    Accept,
    Cancel,
    DataOpen,
    Reject,
    Resume,
    Verified,
)
from teleport.core.transfer import (
    DATA_FAIL_REPORT_AFTER,
    DATA_OPEN_WAIT,
    DATA_RETRY_MAX,
    MAX_PENDING_DATA,
    CheckSource,
    CloseData,
    DataUnreachable,
    FailureDetail,
    OpenData,
    Outcome,
    ReceiveBlocks,
    SendBlocks,
    TransferStatus,
)

EPS = 1e-6
HYPO = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def retry_delay(k: int) -> float:
    """Lịch spec mục 2.2 với hằng mặc định: 1, 2, 4, 8, 16, 30, 30…"""
    return min(1.0 * 2 ** min(k - 1, 20), 30.0)


def test_constants_have_spec_values():
    assert transfer.SYNC_EVERY == 16
    assert transfer.MAX_BAD_BLOCKS == 3
    assert transfer.MAX_VERIFY_FAILURES == 3
    assert transfer.MAX_QUEUED_OFFERS == 8
    assert MAX_PENDING_DATA == 2
    assert DATA_OPEN_WAIT == 10.0
    assert (transfer.DATA_RETRY_BASE, DATA_RETRY_MAX) == (1.0, 30.0)
    assert DATA_FAIL_REPORT_AFTER == 3
    assert transfer.RECONNECT_GRACE == 86400.0  # spec-p3 P3-0: nối lại tới 24 giờ (protocol §6.2)
    # soat-code P3-0: bảng nhớ sống lâu hơn hạn nối lại của máy kia cộng độ lệch phát hiện mất kết
    # nối (keepalive); giá trị cụ thể kiểm theo protocol §6.3 ở test_transfer_params.
    assert transfer.REMEMBER_TTL > transfer.RECONNECT_GRACE + keepalive.DEAD_AFTER
    assert transfer.MAX_REMEMBERED == 1024


# ---- AC-5: bảng §6.3 cột “Gửi” --------------------------------------------------------------------


def test_offer_is_sent_on_send_when_connected(tx):
    s = tx.Send(tx.entries(2, 1))
    acts = s.start(accept=False)
    assert tx.sent(acts) == [s.offer]
    assert tx.statuses(acts, s.key) == [TransferStatus.WAITING]


def test_rule1_resume_of_tombstoned_transfer_gets_same_cancel(tx):
    s = tx.Send(tx.entries(2))
    s.start()
    s.call("cancel", s.key)
    acts = s.resume(0)
    assert tx.sent(acts) == [Cancel(transfer_id=s.T, reason="user")]
    assert not tx.of(acts, (OpenData, SendBlocks))


def test_rule1_data_open_of_tombstoned_transfer_gets_cancel_then_close(tx):
    s = tx.Send(tx.entries(2), client=False)
    s.start()
    s.msg(Cancel(transfer_id=s.T, reason="source_changed"))  # bia mộ lý do của máy kia
    did, acts = s.open(0, 1)
    assert [type(a) for a in acts] == [tx.tr.SendMessage, CloseData]
    assert acts[0].message == Cancel(transfer_id=s.T, reason="source_changed")
    assert acts[1] == CloseData(device_id=tx.PEER, data_id=did)


def test_rule2_resume_of_unknown_transfer_gets_unknown_transfer(tx):
    s = tx.Send(tx.entries(1))
    s.up()
    acts = s.resume(0)
    assert tx.sent(acts) == [Cancel(transfer_id=s.T, reason="unknown_transfer")]
    assert tx.events(acts) == []


def test_rule2_data_open_of_unknown_transfer_gets_cancel_then_close(tx):
    s = tx.Send(tx.entries(1), client=False)
    s.up()
    did, acts = s.open(0, 1)
    assert [type(a) for a in acts] == [tx.tr.SendMessage, CloseData]
    assert acts[0].message == Cancel(transfer_id=s.T, reason="unknown_transfer")
    assert acts[1].data_id == did


@pytest.mark.parametrize(
    "msg",
    [
        Accept(transfer_id="9" * 32),
        Reject(transfer_id="9" * 32, reason="user"),
        Verified(transfer_id="9" * 32, file_index=0),
    ],
)
def test_rule3_answers_for_unknown_transfer_are_ignored(tx, msg):
    s = tx.Send(tx.entries(1))
    s.start()
    assert s.msg(msg) == []


def test_rule3_duplicate_accept_is_ignored(tx):
    s = tx.Send(tx.entries(1))
    s.start()
    assert s.msg(Accept(transfer_id=s.T)) == []


def test_rule3_duplicate_verified_is_ignored(tx):
    s = tx.Send(tx.entries(1, 1))
    s.start()
    s.serve_file(0)
    acts = s.msg(Verified(transfer_id=s.T, file_index=0))
    assert [e.file_index for e in tx.events(acts, tx.tr.FileVerified)] == [0]
    assert s.msg(Verified(transfer_id=s.T, file_index=0)) == []


@pytest.mark.parametrize("msg_kind", ["accept", "reject", "verified"])
def test_rule3_answers_for_ended_transfer_are_ignored(tx, msg_kind):
    s = tx.Send(tx.entries(1))
    s.start()
    s.serve_file(0)
    assert tx.ended(s.msg(Verified(transfer_id=s.T, file_index=0)))
    msg = {
        "accept": Accept(transfer_id=s.T),
        "reject": Reject(transfer_id=s.T, reason="user"),
        "verified": Verified(transfer_id=s.T, file_index=0),
    }[msg_kind]
    assert s.msg(msg) == []


@pytest.mark.parametrize("client", [True, False])
def test_rule4_resume_is_served_before_accept(tx, client):
    s = tx.Send(tx.entries(2), client=client)
    s.start(accept=False)
    acts = s.resume(0)
    assert tx.statuses(acts, s.key) == [TransferStatus.TRANSFERRING]  # `accept` coi như đã mất
    if client:
        assert tx.one(acts, OpenData).message == DataOpen(transfer_id=s.T, file_index=0, resume_seq=1)
    did, acts = s.open(0, 1)
    sb = tx.one(acts, SendBlocks)
    assert (sb.data_id, sb.transfer_id, sb.file_index, sb.size) == (did, s.T, 0, s.files[0].size)
    assert list(sb.have.missing()) == [0, 1]


def test_rule4_resume_of_verified_file_resends_that_file(tx):
    s = tx.Send(tx.entries(2, 1), client=False)
    s.start()
    s.serve_file(0)
    s.msg(Verified(transfer_id=s.T, file_index=0))
    # Bên nhận khởi động lại: xin lại file 0 từ đầu.
    acts = s.resume(0)
    assert tx.sent(acts) == []
    did, acts = s.open(0, s.seq)
    assert list(tx.one(acts, SendBlocks).have.missing()) == [0, 1]
    acts = s.read(did, 0, [0, 1])
    assert tx.sent(acts) == []
    assert tx.one(acts, CheckSource).file_index == 0
    acts = s.check(acts)
    assert tx.sent(acts) == [tx.Complete(transfer_id=s.T, file_index=0, merkle_root=s.root(0).hex())]


def test_rule4_full_resume_resends_complete(tx):
    s = tx.Send(tx.entries(2))
    s.start()
    s.serve_file(0)
    acts = s.resume(0, tx.bits(2, [0, 1]))
    assert tx.sent(acts) == [tx.Complete(transfer_id=s.T, file_index=0, merkle_root=s.root(0).hex())]
    assert not tx.of(acts, (OpenData, SendBlocks))


def test_reject_after_accept_ends_rejected(tx):
    s = tx.Send(tx.entries(3), client=False)
    s.start()
    s.resume(0)
    did, _ = s.open(0, 1)
    rej = Reject(transfer_id=s.T, reason="no_space", needed=10, available=1)
    acts = s.msg(rej)
    assert CloseData(device_id=tx.PEER, data_id=did) in acts
    assert tx.sent(acts) == []
    end = tx.one(tx.ended(acts), object)
    assert (end.outcome, end.reason, end.by_peer, end.reject) == (Outcome.REJECTED, "no_space", True, rej)
    assert s.e.info(s.key) is None


def test_verified_for_file_without_root_cancels(tx):
    s = tx.Send(tx.entries(3, 1), client=False)
    s.start()
    s.resume(0)
    did, _ = s.open(0, 1)
    s.read(did, 0, [0])  # file 0 chưa đọc hết: chưa có root
    acts = s.msg(Verified(transfer_id=s.T, file_index=0))
    assert tx.sent(acts) == [Cancel(transfer_id=s.T, reason="error")]
    end = tx.one(tx.ended(acts), object)
    assert (end.outcome, end.reason, end.by_peer, end.detail, end.file_index) == (
        Outcome.CANCELLED,
        "error",
        False,
        FailureDetail.PROTOCOL,
        0,
    )
    assert CloseData(device_id=tx.PEER, data_id=did) in acts


def test_verified_for_never_served_file_cancels(tx):
    s = tx.Send(tx.entries(1, 1))
    s.start()
    acts = s.msg(Verified(transfer_id=s.T, file_index=1))
    assert tx.sent(acts) == [Cancel(transfer_id=s.T, reason="error")]
    assert tx.one(tx.ended(acts), object).file_index == 1


def test_verified_of_last_file_ends_done_and_marks_all_files(tx):
    s = tx.Send(tx.entries(1, 2, 1))
    s.start()
    s.serve_file(0)
    s.msg(Verified(transfer_id=s.T, file_index=0))
    s.serve_file(1)  # `verified(1)` bị mất
    s.serve_file(2)
    acts = s.msg(Verified(transfer_id=s.T, file_index=2))
    fv = tx.events(acts, tx.tr.FileVerified)
    assert [(e.key, e.file_index, e.name) for e in fv] == [
        (s.key, 1, s.files[1].name),
        (s.key, 2, s.files[2].name),
    ]
    end = tx.one(tx.ended(acts), object)
    assert end.outcome == Outcome.DONE
    assert s.e.info(s.key) is None
    assert s.e.transfers() == ()
    # G5: FileVerified trước TransferEnded (cả hai là Report, không phải StatusChanged).
    reports = [a.event for a in acts if isinstance(a, tx.tr.Report)]
    assert reports.index(fv[-1]) < reports.index(end)


def test_verified_of_last_file_when_all_earlier_verified_lost(tx):
    s = tx.Send(tx.entries(1, 1, 1))
    s.start()
    for f in range(3):
        s.serve_file(f)
    acts = s.msg(Verified(transfer_id=s.T, file_index=2))
    assert [e.file_index for e in tx.events(acts, tx.tr.FileVerified)] == [0, 1, 2]
    assert tx.one(tx.ended(acts), object).outcome == Outcome.DONE


def test_verified_beyond_files_cancels_with_no_file_index(tx):
    s = tx.Send(tx.entries(1, 1))
    s.start()
    s.serve_file(0)
    acts = s.msg(Verified(transfer_id=s.T, file_index=5))
    assert tx.sent(acts) == [Cancel(transfer_id=s.T, reason="error")]
    end = tx.one(tx.ended(acts), object)
    assert (end.detail, end.file_index) == (FailureDetail.PROTOCOL, None)


def test_verified_of_middle_file_releases_it_and_reports(tx):
    s = tx.Send(tx.entries(1, 1))
    s.start()
    s.serve_file(0)
    acts = s.msg(Verified(transfer_id=s.T, file_index=0))
    assert [(e.file_index, e.name) for e in tx.events(acts, tx.tr.FileVerified)] == [(0, s.files[0].name)]
    assert tx.ended(acts) == []
    info = s.e.info(s.key)
    assert info.file_index == 1
    assert info.done_bytes == s.files[0].size


# ---- AC-7: seq / data_open --------------------------------------------------------------------


def test_server_sender_serves_only_matching_resume(tx):
    s = tx.Send(tx.entries(2, 2), client=False)
    s.start()
    s.resume(0)  # seq 1, file 0
    d_wrong_file, acts = s.open(1, 1)
    assert acts == [CloseData(device_id=tx.PEER, data_id=d_wrong_file)]
    d_ok, acts = s.open(0, 1)
    assert tx.one(acts, SendBlocks).data_id == d_ok


def test_data_open_with_old_seq_is_closed(tx):
    s = tx.Send(tx.entries(2), client=False)
    s.start()
    s.resume(0, seq=1)
    s.resume(0, seq=2)
    did, acts = s.open(0, 1)
    assert acts == [CloseData(device_id=tx.PEER, data_id=did)]


def test_data_open_before_resume_waits_then_is_served(tx):
    s = tx.Send(tx.entries(2), client=False)
    s.start()
    did, acts = s.open(0, 1)
    assert acts == []
    acts = s.resume(0, seq=1)
    sb = tx.one(acts, SendBlocks)
    assert (sb.data_id, sb.file_index) == (did, 0)
    assert s.e.next_wakeup() is None


def test_pending_data_open_times_out_only_in_tick(tx):
    s = tx.Send(tx.entries(2), client=False)
    s.start()
    t0 = s.now + 1.0
    acts = s.call(
        "incoming_data", tx.PEER, 300, DataOpen(transfer_id=s.T, file_index=0, resume_seq=1), now=t0
    )
    assert acts == []
    assert s.e.next_wakeup() == t0 + DATA_OPEN_WAIT
    assert s.tick(now=t0 + DATA_OPEN_WAIT - EPS) == []
    acts = s.tick(now=t0 + DATA_OPEN_WAIT)
    assert acts == [CloseData(device_id=tx.PEER, data_id=300)]
    assert s.e.next_wakeup() is None
    # `resume` tới sau đó: kết nối đã đóng, không có SendBlocks cho nó.
    acts = s.resume(0, seq=1)
    assert not tx.of(acts, SendBlocks)


def test_pending_data_open_with_deadline_equal_now_is_served_without_tick(tx):
    s = tx.Send(tx.entries(2), client=False)
    s.start()
    t0 = s.now + 1.0
    s.call("incoming_data", tx.PEER, 300, DataOpen(transfer_id=s.T, file_index=0, resume_seq=1), now=t0)
    acts = s.resume(0, seq=1, now=t0 + DATA_OPEN_WAIT)
    assert tx.one(acts, SendBlocks).data_id == 300


def test_third_pending_connection_replaces_lowest_or_is_closed(tx):
    s = tx.Send(tx.entries(2), client=False)
    s.start()
    d3, acts = s.open(0, 3)
    assert acts == []
    d5, acts = s.open(0, 5)
    assert acts == []
    d4, acts = s.open(0, 4)  # 4 > 3 (nhỏ nhất đang chờ): đóng kết nối seq 3, giữ kết nối mới
    assert acts == [CloseData(device_id=tx.PEER, data_id=d3)]
    d2, acts = s.open(0, 2)  # 2 < 4: đóng kết nối mới
    assert acts == [CloseData(device_id=tx.PEER, data_id=d2)]
    d4b, acts = s.open(0, 4)  # bằng nhỏ nhất: không lớn hơn → đóng kết nối mới
    assert acts == [CloseData(device_id=tx.PEER, data_id=d4b)]
    acts = s.resume(0, seq=4)
    assert tx.one(acts, SendBlocks).data_id == d4
    acts = s.resume(0, seq=5)  # `resume` mới đóng kết nối phục vụ `resume` cũ (G4)
    i_close = acts.index(CloseData(device_id=tx.PEER, data_id=d4))
    i_send = tx.index_of(acts, lambda a: isinstance(a, SendBlocks) and a.data_id == d5)
    assert i_close < i_send


def test_pending_limit_is_per_device(tx):
    s = tx.Send(tx.entries(2), client=False)
    c = tx.Send(tx.entries(2), T=tx.T2, peer=tx.OTHER, like=s, cid=2, client=False)
    s.start()
    c.start()
    for seq in (3, 4):
        assert s.open(0, seq)[1] == []
    for seq in (3, 4):
        assert c.open(0, seq)[1] == []


@pytest.mark.parametrize("known", [True, False])
def test_data_open_in_wrong_direction_is_only_closed(tx, known):
    s = tx.Send(tx.entries(2), client=True)  # máy này là client của kết nối điều khiển
    if known:
        s.start()
    else:
        s.up()
    did = 400
    acts = s.call("incoming_data", tx.PEER, did, DataOpen(transfer_id=s.T, file_index=0, resume_seq=1))
    assert acts == [CloseData(device_id=tx.PEER, data_id=did)]


def test_data_open_without_control_connection_is_only_closed(tx):
    s = tx.Send(tx.entries(2), client=False)
    s.call("send", tx.PEER, s.T, list(s.files))
    acts = s.call("incoming_data", tx.PEER, 401, DataOpen(transfer_id=s.T, file_index=0, resume_seq=1))
    assert acts == [CloseData(device_id=tx.PEER, data_id=401)]


def test_other_device_cannot_use_transfer_id_of_peer(tx):
    s = tx.Send(tx.entries(2), client=False)
    s.start()
    before = s.e.info(s.key)
    c = tx.Driver(s.e, tx.OTHER, cid=9, clock=s.clock)
    c.up()
    acts = c.call("incoming_data", tx.OTHER, 500, DataOpen(transfer_id=s.T, file_index=0, resume_seq=1))
    assert acts == [
        tx.tr.SendMessage(
            device_id=tx.OTHER, control_id=9, message=Cancel(transfer_id=s.T, reason="unknown_transfer")
        ),
        CloseData(device_id=tx.OTHER, data_id=500),
    ]
    acts = c.msg(Resume(transfer_id=s.T, file_index=0, seq=1, bitfield=Bitfield(2).to_base64()))
    assert tx.sent(acts) == [Cancel(transfer_id=s.T, reason="unknown_transfer")]
    assert c.msg(Cancel(transfer_id=s.T, reason="user")) == []
    assert c.msg(Verified(transfer_id=s.T, file_index=1)) == []
    assert s.e.info(s.key) == before
    # Lượt của PEER vẫn chạy bình thường.
    s.resume(0)
    _, acts = s.open(0, 1)
    assert tx.one(acts, SendBlocks).transfer_id == s.T


def test_receiver_client_sends_resume_then_opens_with_same_seq(tx):
    r = tx.Recv(tx.entries(3), client=True)
    acts = r.accept()
    res = tx.one(tx.sent(acts, Resume), object)
    od = tx.one(acts, OpenData)
    assert od.message == DataOpen(transfer_id=r.T, file_index=0, resume_seq=res.seq)
    assert od.control_id == r.cid
    i_res = tx.index_of(acts, lambda a: isinstance(a, tx.tr.SendMessage) and a.message == res)
    assert i_res < acts.index(od)  # G3


def test_receiver_server_accepts_only_latest_resume(tx):
    r = tx.Recv(tx.entries(3, 2))
    r.accept()  # resume seq 1, file 0
    assert r.open(seq=2)[1] == [CloseData(device_id=tx.PEER, data_id=r._did)]
    assert r.open(f=1)[1] == [CloseData(device_id=tx.PEER, data_id=r._did)]
    did, acts = r.open()
    assert tx.one(acts, ReceiveBlocks) == ReceiveBlocks(
        device_id=tx.PEER, data_id=did, transfer_id=r.T, file_index=0, size=r.files[0].size
    )
    acts = r.call("block_bad", tx.PEER, did)  # xin `resume` mới (seq 2)
    assert tx.one(tx.sent(acts, Resume), object).seq == 2
    assert r.open(seq=1)[1] == [CloseData(device_id=tx.PEER, data_id=r._did)]
    assert tx.one(r.open(seq=2)[1], ReceiveBlocks).file_index == 0


def test_receiver_server_rejects_data_open_when_last_resume_was_full(tx):
    r = tx.Recv(tx.entries(1, 1))
    r.accept()
    did, _ = r.open()
    r.sync_all(r.feed(did, 0, [0]))
    r.call("data_closed", tx.PEER, did, False)
    r.lost()
    acts = r.up(cid=2)  # `resume` đủ bit: không mở kết nối dữ liệu
    res = tx.one(tx.sent(acts, Resume), object)
    assert tx.bits_on(res.bitfield, 1) == {0}
    assert r.e.next_wakeup() is None  # `resume` đủ bit: không chờ `data_open` (protocol §4.1)
    assert r.open(seq=res.seq)[1] == [CloseData(device_id=tx.PEER, data_id=r._did)]


@pytest.mark.parametrize("client", [False, True])
def test_new_resume_closes_connection_serving_old_resume(tx, client):
    s = tx.Send(tx.entries(3), client=client)
    s.start()
    s.resume(0)
    d1, acts = s.open(0, 1)
    assert tx.one(acts, SendBlocks).data_id == d1
    acts = s.resume(0, tx.bits(3, []))
    assert CloseData(device_id=tx.PEER, data_id=d1) in acts
    if client:
        od = tx.one(acts, OpenData)
        assert od.message.resume_seq == 2
        assert acts.index(CloseData(device_id=tx.PEER, data_id=d1)) < acts.index(od)


def test_stale_resume_with_lower_seq_is_ignored(tx):
    s = tx.Send(tx.entries(3), client=True)
    s.start()
    s.resume(0, seq=2)
    assert s.resume(0, seq=2) == []
    assert s.resume(0, seq=1) == []


def test_resume_with_max_safe_seq_is_served(tx):
    s = tx.Send(tx.entries(2), client=True)
    s.start()
    acts = s.resume(0, seq=MAX_SAFE_INTEGER)
    assert tx.one(acts, OpenData).message.resume_seq == MAX_SAFE_INTEGER
    _, acts = s.open(0, MAX_SAFE_INTEGER)
    assert tx.one(acts, SendBlocks).file_index == 0
    assert s.resume(0, seq=5) == []


def test_pending_data_open_with_max_safe_seq_waits_for_resume(tx):
    s = tx.Send(tx.entries(2), client=False)
    s.start()
    did, acts = s.open(0, MAX_SAFE_INTEGER)
    assert acts == []
    acts = s.resume(0, seq=MAX_SAFE_INTEGER)
    assert tx.one(acts, SendBlocks).data_id == did


def test_interleaved_resumes_of_two_devices_keep_separate_seq(tx):
    s = tx.Send(tx.entries(3), client=True)
    c = tx.Send(tx.entries(2), T=tx.T2, peer=tx.OTHER, like=s, cid=2, client=True)
    s.start()
    c.start()
    a1 = s.resume(0, seq=1)
    b1 = c.resume(0, seq=1)
    a2 = s.resume(0, seq=2)
    b2 = c.resume(0, seq=2)
    b_old = c.resume(0, seq=1)
    assert tx.one(a1, OpenData) == OpenData(
        device_id=tx.PEER, control_id=1, message=DataOpen(transfer_id=s.T, file_index=0, resume_seq=1)
    )
    assert tx.one(b1, OpenData) == OpenData(
        device_id=tx.OTHER, control_id=2, message=DataOpen(transfer_id=c.T, file_index=0, resume_seq=1)
    )
    assert tx.one(a2, OpenData).message.resume_seq == 2
    assert tx.one(b2, OpenData).message.resume_seq == 2
    assert b_old == []
    _, acts = s.open(0, 2)
    assert tx.one(acts, SendBlocks).transfer_id == s.T
    _, acts = c.open(0, 1)  # `resume` 1 của OTHER đã cũ
    assert tx.of(acts, SendBlocks) == []
    _, acts = c.open(0, 2)
    assert tx.one(acts, SendBlocks).transfer_id == c.T


def _fail_and_reopen(tx, s, msg, *, expect_open: bool = True):
    acts = s.call("outgoing_data_failed", tx.PEER, s.cid, msg)
    fail_time = s.now
    w = s.e.next_wakeup()
    reopen = s.tick(now=w) if w is not None else []
    if expect_open:
        assert tx.one(reopen, OpenData).message == msg
    return acts, w - fail_time if w is not None else None, reopen


def test_sender_client_reports_unreachable_once_after_three_failures(tx):
    s = tx.Send(tx.entries(3), client=True)
    s.start()
    msg = tx.one(s.resume(0), OpenData).message
    for k in range(1, DATA_FAIL_REPORT_AFTER):
        acts, _, _ = _fail_and_reopen(tx, s, msg)
        assert tx.events(acts, DataUnreachable) == []
        assert s.e.info(s.key).status == TransferStatus.TRANSFERRING, k
    acts, _, _ = _fail_and_reopen(tx, s, msg)
    assert tx.events(acts, DataUnreachable) == [DataUnreachable(device_id=tx.PEER)]
    assert tx.statuses(acts, s.key) == [TransferStatus.RECONNECTING]
    acts, _, _ = _fail_and_reopen(tx, s, msg)
    assert tx.events(acts, DataUnreachable) == []
    # Mở được: về TRANSFERRING, bộ đếm lỗi về 0.
    did, acts = s.open(0, 1)
    assert tx.one(acts, SendBlocks).data_id == did
    assert tx.statuses(acts, s.key) == [TransferStatus.TRANSFERRING]
    acts = s.call("data_closed", tx.PEER, did, False)  # đứt trước khi gửi hết: mở lại cùng `data_open`
    assert tx.one(s.tick(now=s.e.next_wakeup()), OpenData).message == msg
    for _ in range(DATA_FAIL_REPORT_AFTER - 1):
        acts, _, _ = _fail_and_reopen(tx, s, msg)
        assert tx.events(acts, DataUnreachable) == []
        assert s.e.info(s.key).status == TransferStatus.TRANSFERRING
    acts, _, _ = _fail_and_reopen(tx, s, msg)
    assert tx.events(acts, DataUnreachable) == [DataUnreachable(device_id=tx.PEER)]
    assert s.e.info(s.key).status == TransferStatus.RECONNECTING


def test_receiver_client_reports_unreachable_and_sends_new_resume_each_retry(tx):
    r = tx.Recv(tx.entries(3), client=True)
    acts = r.accept()
    msg = tx.one(acts, OpenData).message
    seqs = [msg.resume_seq]
    for k in range(1, DATA_FAIL_REPORT_AFTER + 1):
        acts = r.call("outgoing_data_failed", tx.PEER, r.cid, msg)
        if k < DATA_FAIL_REPORT_AFTER:
            assert tx.events(acts, DataUnreachable) == []
            assert r.e.info(r.key).status == TransferStatus.TRANSFERRING
        else:
            assert tx.events(acts, DataUnreachable) == [DataUnreachable(device_id=tx.PEER)]
            assert tx.statuses(acts, r.key) == [TransferStatus.RECONNECTING]
        # `outgoing_data_failed` của `data_open` cũ không còn khớp: bỏ qua, không đếm.
        acts = r.tick_due()
        res = tx.one(tx.sent(acts, Resume), object)
        od = tx.one(acts, OpenData)
        assert od.message == DataOpen(transfer_id=r.T, file_index=0, resume_seq=res.seq)
        seqs.append(res.seq)
        stale = msg
        msg = od.message
        assert r.call("outgoing_data_failed", tx.PEER, r.cid, stale) == []
    assert seqs == sorted(set(seqs))
    did, acts = r.open()
    assert tx.one(acts, ReceiveBlocks).data_id == did
    assert tx.statuses(acts, r.key) == [TransferStatus.TRANSFERRING]


@pytest.mark.parametrize("side", ["send", "recv"])
def test_retry_schedule_is_1_2_4_8_16_30_30(tx, side):
    if side == "send":
        d = tx.Send(tx.entries(3), client=True)
        d.start()
        msg = tx.one(d.resume(0), OpenData).message
    else:
        d = tx.Recv(tx.entries(3), client=True)
        msg = tx.one(d.accept(), OpenData).message
    gaps = []
    for _ in range(7):
        d.call("outgoing_data_failed", tx.PEER, d.cid, msg)
        t_fail = d.now
        w = d.e.next_wakeup()
        gaps.append(w - t_fail)
        assert d.tick(now=w - EPS) == []
        acts = d.tick(now=w)
        msg = tx.one(acts, OpenData).message
    assert gaps == pytest.approx([1, 2, 4, 8, 16, 30, 30])


def test_sender_reopens_same_data_open_after_unfinished_close(tx):
    s = tx.Send(tx.entries(3), client=True)
    s.start()
    msg = tx.one(s.resume(0), OpenData).message
    did, _ = s.open(0, 1)
    s.read(did, 0, [0])
    s.call("data_closed", tx.PEER, did, False)
    w = s.e.next_wakeup()
    assert w == pytest.approx(s.now + retry_delay(1))
    assert tx.one(s.tick(now=w), OpenData).message == msg


def test_sender_does_not_reopen_after_finished_close(tx):
    s = tx.Send(tx.entries(1), client=True)
    s.start()
    s.resume(0)
    did, _ = s.open(0, 1)
    acts = s.read(did, 0, [0])
    s.check(acts)
    assert s.call("data_closed", tx.PEER, did, True) == []
    assert s.e.next_wakeup() is None


def test_sender_retry_is_dropped_when_newer_resume_arrives(tx):
    s = tx.Send(tx.entries(3), client=True)
    s.start()
    msg1 = tx.one(s.resume(0), OpenData).message
    s.call("outgoing_data_failed", tx.PEER, s.cid, msg1)
    acts = s.resume(0, seq=2)
    assert tx.one(acts, OpenData).message.resume_seq == 2
    assert s.e.next_wakeup() is None or not tx.of(s.tick(now=s.e.next_wakeup()), OpenData)


# ---- protocol §4.1: server là bên nhận chờ `data_open` -------------------------------------------
# “Server là bên nhận: không nhận được `data_open` khớp `resume` (thiếu khối) vừa gửi trong thời hạn
# đó (10 s) → gửi `resume` mới theo lịch ở mục 6.2. … Lần quá hạn này không tính vào số lần mở thất
# bại để báo lỗi tường lửa: chỉ client mở kết nối dữ liệu, nên chỉ client báo lỗi đó.”
# Spec 3.10 và D40 cũng chỉ cho RECONNECTING khi kết nối điều khiển còn sống nếu máy này là client.


def _until_resume(tx, r, acts):
    """Gọi `tick` đúng hẹn tới khi có `resume` (tối đa 3 lần). Trả (thời điểm, hành động)."""
    for _ in range(3):
        if tx.sent(acts, Resume):
            return r.now, acts
        w = r.e.next_wakeup()
        assert w is not None, "không còn hẹn giờ nào: lượt treo"
        acts = r.tick(now=w)
    raise AssertionError("không có `resume` mới")


def test_receiver_server_sends_new_resume_when_no_data_open_within_wait(tx):
    r = tx.Recv(tx.entries(3))
    r.accept()
    t0 = r.now  # `resume` seq 1 (thiếu khối) gửi lúc này
    assert r.e.next_wakeup() == pytest.approx(t0 + DATA_OPEN_WAIT)
    assert tx.sent(r.tick(now=t0 + DATA_OPEN_WAIT - EPS), Resume) == []
    t1, acts = _until_resume(tx, r, r.tick(now=t0 + DATA_OPEN_WAIT))
    # Lần thất bại đầu tiên: chờ theo lịch §6.2 (1 s) tính từ hạn, không sớm hơn hạn.
    assert t0 + DATA_OPEN_WAIT <= t1 <= t0 + DATA_OPEN_WAIT + retry_delay(1) + EPS
    res = tx.one(tx.sent(acts, Resume), object)
    assert (res.file_index, res.seq) == (0, 2)
    assert tx.of(acts, OpenData) == []  # máy này là server
    assert r.e.info(r.key).status == TransferStatus.TRANSFERRING
    # `data_open` của `resume` cũ bị từ chối; của `resume` mới thì được nhận.
    assert r.open(seq=1)[1] == [CloseData(device_id=tx.PEER, data_id=r._did)]
    did, acts = r.open()
    assert tx.one(acts, ReceiveBlocks).data_id == did


def test_receiver_server_retries_keep_following_schedule(tx):
    """Mỗi lần quá hạn mà không có `data_open` là một vòng không tiến triển liên tiếp: khoảng chờ thêm
    sau hạn 10 s tăng theo lịch §6.2 và không vượt `DATA_RETRY_MAX`. (Vòng này không tính vào số lần
    mở thất bại để báo tường lửa: test ngay dưới.)"""
    r = tx.Recv(tx.entries(3))
    r.accept()
    sent_at = r.now
    gaps = []
    for _ in range(7):
        t, _acts = _until_resume(tx, r, r.tick(now=sent_at + DATA_OPEN_WAIT))
        gaps.append(t - sent_at - DATA_OPEN_WAIT)
        sent_at = t
    assert gaps == pytest.approx([1, 2, 4, 8, 16, 30, 30])
    assert len({res.seq for res in r.resumes()}) == len(r.resumes()) == 8


def test_receiver_server_wait_timeouts_never_report_unreachable_or_reconnecting(tx):
    """Protocol §4.1: lần quá hạn chờ `data_open` của server không tính vào số lần mở thất bại; spec
    2.5 (`DataUnreachable` = mở kết nối dữ liệu thất bại), 3.10 và D40: chỉ client mới sang
    RECONNECTING khi kết nối điều khiển còn sống. Quá hạn nhiều hơn hẳn `DATA_FAIL_REPORT_AFTER` lần
    liên tiếp vẫn không báo tường lửa, lượt vẫn TRANSFERRING, không có `OpenData` nào."""
    r = tx.Recv(tx.entries(3))  # máy này là server của kết nối điều khiển
    r.accept()
    sent_at = r.now
    for _ in range(2 * DATA_FAIL_REPORT_AFTER + 1):
        t, _acts = _until_resume(tx, r, r.tick(now=sent_at + DATA_OPEN_WAIT))
        sent_at = t
        assert r.e.info(r.key).status == TransferStatus.TRANSFERRING
    everything = r.all_actions()
    assert tx.events(everything, DataUnreachable) == []
    assert TransferStatus.RECONNECTING not in tx.statuses(everything, r.key)
    assert tx.of(everything, OpenData) == []
    assert tx.ended(everything) == []
    # Kết nối dữ liệu tới cho `resume` mới nhất vẫn được nhận.
    did, acts = r.open()
    assert tx.one(acts, ReceiveBlocks).data_id == did
    assert tx.statuses(acts, r.key) == []  # vẫn TRANSFERRING, không đổi trạng thái


def test_receiver_server_wait_ends_when_matching_data_open_arrives(tx):
    r = tx.Recv(tx.entries(3))
    r.accept()
    t0 = r.now
    did, acts = r.open()
    assert tx.one(acts, ReceiveBlocks).data_id == did
    assert r.e.next_wakeup() is None
    assert tx.sent(r.tick(now=t0 + DATA_OPEN_WAIT + DATA_RETRY_MAX), Resume) == []


def test_receiver_server_late_data_open_cancels_scheduled_resume(tx):
    """`data_open` khớp `resume` mới nhất tới sau hạn chờ (`tick` đã hẹn `resume` mới) vẫn được nhận,
    và hẹn đó bị hủy: kết nối đang nhận khối tốt không bị cắt, không có `resume` mới."""
    r = tx.Recv(tx.entries(3))
    r.accept()
    t0 = r.now
    assert tx.sent(r.tick(now=t0 + DATA_OPEN_WAIT), Resume) == []  # chỉ hẹn `resume` mới
    assert r.e.next_wakeup() is not None
    did, acts = r.open()
    assert tx.one(acts, ReceiveBlocks).data_id == did
    r.feed(did, 0, [0])
    assert r.e.next_wakeup() is None
    acts = r.tick(now=t0 + DATA_OPEN_WAIT + DATA_RETRY_MAX)
    assert tx.of(acts, CloseData) == []
    assert tx.sent(acts, Resume) == []


def test_receiver_server_data_open_at_wait_deadline_without_tick_is_served(tx):
    """Spec 3.14: hạn chót chỉ xử lý trong `tick`; `data_open` tới đúng lúc hạn, chưa `tick` → nhận."""
    r = tx.Recv(tx.entries(3))
    r.accept()
    w = r.e.next_wakeup()
    msg = DataOpen(transfer_id=r.T, file_index=0, resume_seq=1)
    acts = r.call("incoming_data", tx.PEER, 555, msg, now=w)
    assert tx.one(acts, ReceiveBlocks).data_id == 555
    assert tx.sent(r.tick(now=w), Resume) == []


def test_receiver_client_has_no_data_open_wait(tx):
    """Client là bên nhận: lần mở thất bại do app báo (`outgoing_data_failed`), engine không tự hẹn."""
    r = tx.Recv(tx.entries(3), client=True)
    r.accept()
    assert r.e.next_wakeup() is None


# ---- AC-8: chỉ gửi khối có bit = 0 (hypothesis) -------------------------------------------------


@HYPO
@given(data=st.data())
def test_send_blocks_have_is_exactly_the_resume_bitfield(tx, data):
    n = data.draw(st.integers(1, 70), label="n")
    client = data.draw(st.booleans(), label="client")
    s = tx.Send(tx.entries(n), client=client)
    s.start()
    # Lần phục vụ đầu: đọc một phần đầu (kết nối có thể đứt giữa chừng).
    s.resume(0)
    did, acts = s.open(0, s.seq)
    first = tx.one(acts, SendBlocks)
    assert first.have == Bitfield(n)
    read_upto = data.draw(st.integers(0, n), label="read_upto")
    acts = s.read(did, 0, range(read_upto))
    s.check(acts)
    s.call("data_closed", tx.PEER, did, read_upto == n)
    sent_set = set(range(read_upto))
    # `resume` với bitfield bất kỳ.
    on = data.draw(st.sets(st.integers(0, n - 1)), label="have")
    have = tx.bits(n, on)
    acts = s.resume(0, have)
    if not on <= sent_set:
        assert tx.sent(acts) == [Cancel(transfer_id=s.T, reason="error")]  # bên nhận khai khối chưa từng gửi
        assert tx.one(tx.ended(acts), object).detail == FailureDetail.PROTOCOL
        return
    if have.all_set():
        assert not tx.of(acts, (OpenData, SendBlocks))
        assert tx.sent(acts) == [tx.Complete(transfer_id=s.T, file_index=0, merkle_root=s.root(0).hex())]
        return
    did2, acts = s.open(0, s.seq)
    sb = tx.one(acts, SendBlocks)
    assert sb.have == have
    # Bộ thực thi giả: chỉ đọc khối trong `have.missing()`; engine không phản đối khối nào.
    missing = list(sb.have.missing())
    assert missing == sorted(set(range(n)) - on)
    for i in missing:
        out = s.call("block_read", tx.PEER, did2, i, s.dg(0, i))
        assert not tx.of(out, CloseData)
        assert tx.sent(out) == []


# ---- AC-23: lịch thử lại dài, hạn chót -----------------------------------------------------------


def test_ten_thousand_failed_opens_never_overflow(tx):
    s = tx.Send(tx.entries(2), client=True)
    s.start()
    msg = tx.one(s.resume(0), OpenData).message
    unreachable = 0
    last_open = s.now
    for _ in range(10_000):
        # Lần mở thất bại ngay lúc mở: khoảng cách giữa hai lần mở = lịch thử lại.
        acts = s.call("outgoing_data_failed", tx.PEER, s.cid, msg, now=last_open)
        unreachable += len(tx.events(acts, DataUnreachable))
        w = s.e.next_wakeup()
        assert w is not None
        acts = s.tick(now=w)
        assert tx.one(acts, OpenData).message == msg
        assert w - last_open <= DATA_RETRY_MAX + EPS
        last_open = w
    assert unreachable == 1
    assert s.e.info(s.key).status == TransferStatus.RECONNECTING


def test_engine_with_only_tombstones_has_no_wakeup(tx):
    s = tx.Send(tx.entries(2), client=True)
    s.start()
    s.resume(0)
    s.call("cancel", s.key)
    assert s.e.next_wakeup() is None
    r = tx.Recv(tx.entries(1))
    r.accept()
    r.lost()
    r.tick(now=r.now + transfer.RECONNECT_GRACE)
    assert r.e.transfers() == ()
    assert r.e.next_wakeup() is None


def test_retry_constants_are_read_at_use(tx, monkeypatch):
    monkeypatch.setattr(transfer, "DATA_RETRY_BASE", 0.25)
    monkeypatch.setattr(transfer, "DATA_RETRY_MAX", 0.5)
    s = tx.Send(tx.entries(2), client=True)
    s.start()
    msg = tx.one(s.resume(0), OpenData).message
    gaps = []
    for _ in range(3):
        s.call("outgoing_data_failed", tx.PEER, s.cid, msg)
        gaps.append(s.e.next_wakeup() - s.now)
        s.tick(now=s.e.next_wakeup())
    assert gaps == pytest.approx([0.25, 0.5, 0.5])


def test_data_open_wait_is_read_at_use(tx, monkeypatch):
    monkeypatch.setattr(transfer, "DATA_OPEN_WAIT", 2.0)
    s = tx.Send(tx.entries(2), client=False)
    s.start()
    t0 = s.now + 1
    s.call("incoming_data", tx.PEER, 300, DataOpen(transfer_id=s.T, file_index=0, resume_seq=1), now=t0)
    assert s.e.next_wakeup() == t0 + 2.0


def test_data_open_for_file_beyond_offer_is_closed(tx):
    s = tx.Send(tx.entries(2), client=False)
    s.start()
    s.resume(0)
    did, acts = s.open(1, 1)  # lượt chỉ có 1 file
    assert acts == [CloseData(device_id=tx.PEER, data_id=did)]


def test_resume_of_verified_file_claiming_blocks_is_protocol_error(tx):
    # Spec 3.4 `resume` bước 7–8: file đã `verified` được cấp trạng thái mới, nên bitfield có bit nào
    # cũng là “khai khối chưa từng gửi”.
    s = tx.Send(tx.entries(2, 1))
    s.start()
    s.serve_file(0)
    s.msg(Verified(transfer_id=s.T, file_index=0))
    acts = s.resume(0, tx.bits(2, [0]))
    assert tx.sent(acts) == [Cancel(transfer_id=s.T, reason="error")]
    assert tx.one(tx.ended(acts), object).detail == FailureDetail.PROTOCOL


def test_control_up_drops_scheduled_reopen_of_sender(tx):
    s = tx.Send(tx.entries(2), client=True)
    s.start()
    msg = tx.one(s.resume(0), OpenData).message
    s.call("outgoing_data_failed", tx.PEER, s.cid, msg)
    assert s.e.next_wakeup() is not None
    s.up(cid=2)
    assert s.e.next_wakeup() is None


def test_control_up_replaces_scheduled_resume_of_receiver(tx):
    r = tx.Recv(tx.entries(2), client=True)
    msg = tx.one(r.accept(), OpenData).message
    r.call("outgoing_data_failed", tx.PEER, r.cid, msg)
    assert r.e.next_wakeup() is not None
    acts = r.up(cid=2, client=True)
    assert tx.one(tx.sent(acts, Resume), object).seq == 1
    assert tx.one(acts, OpenData).control_id == 2
    assert r.e.next_wakeup() is None
