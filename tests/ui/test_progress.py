"""`teleport.ui.progress`: % tổng của một đợt và nhịp đổi tiêu đề (spec-f4 mục 2.2, 2.3; mục 8 S10, S19
thắng khi khác). Tiêu chí R1, R2.

Viết từ spec, không từ code. Hàm thuần, không Qt: `now` giả truyền thẳng vào `ProgressThrottle`. Hằng
cấp module đọc lúc dùng (spec mục 2.1) nên test vá được bằng `monkeypatch`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# =================================================================================================
# Dữ liệu giả
# =================================================================================================

STATES = ("moving", "done", "failed", "waiting", "queued_send", "queued_receive", "reconnecting")


def item(key, shown: int, total: int, state: str = "moving"):
    """`ProgressItem` như `TransfersController` dựng từ một bong bóng.

    `state`: moving (TRANSFERRING/VERIFYING), done (kết thúc DONE), failed (kết thúc khác DONE), waiting,
    queued_send (QUEUED chiều gửi), queued_receive (QUEUED chiều nhận), reconnecting.
    """
    from teleport.ui.progress import ProgressItem

    assert state in STATES
    return ProgressItem(
        key=key,
        shown=shown,
        total=total,
        finished=state in ("done", "failed"),
        done=state == "done",
        moving=state == "moving",
        queued_send=state == "queued_send",
    )


@pytest.fixture
def batch():
    from teleport.ui.progress import ProgressBatch

    return ProgressBatch()


@pytest.fixture
def throttle():
    from teleport.ui.progress import ProgressThrottle

    return ProgressThrottle()


def changes(values: list) -> int:
    """Số lần giá trị hiển thị đổi (tính cả lần đầu từ None sang số)."""
    count, last = 0, None
    for v in values:
        if v != last:
            count += 1
            last = v
    return count


# =================================================================================================
# R1: ProgressBatch
# =================================================================================================


def test_two_moving_transfers_give_byte_weighted_percent(batch):
    assert batch.update([item("a", 50, 100), item("b", 150, 300)]) == 50


def test_done_member_counts_full_total(batch):
    assert batch.update([item("a", 50, 100), item("b", 0, 300)]) == 12
    assert batch.update([item("a", 100, 100, "done"), item("b", 0, 300)]) == 25


def test_done_member_counts_total_even_if_shown_lags(batch):
    batch.update([item("a", 10, 100), item("b", 0, 300)])
    assert batch.update([item("a", 10, 100, "done"), item("b", 0, 300)]) == 25


@pytest.mark.parametrize("state", ["waiting", "queued_send", "queued_receive", "reconnecting"])
def test_only_never_moving_transfers_give_none(batch, state):
    assert batch.update([item("a", 0, 100, state), item("b", 30, 100, state)]) is None


def test_empty_update_gives_none(batch):
    assert batch.update([]) is None


def test_failed_member_leaves_numerator_and_denominator(batch):
    assert batch.update([item("a", 50, 100), item("b", 0, 300)]) == 12
    assert batch.update([item("a", 50, 100), item("b", 120, 300, "failed")]) == 50


def test_all_finished_gives_none_and_next_batch_starts_empty(batch):
    batch.update([item("a", 50, 100), item("b", 0, 300)])
    assert batch.update([item("a", 100, 100, "done"), item("b", 300, 300, "done")]) is None
    # Bong bóng cũ vẫn còn trên màn hình: đợt mới không tính chúng.
    assert batch.update([item("a", 100, 100, "done"), item("b", 300, 300, "done"), item("c", 10, 100)]) == 10


def test_all_failed_gives_none(batch):
    batch.update([item("a", 50, 100)])
    assert batch.update([item("a", 50, 100, "failed")]) is None


def test_never_reaches_100_before_finish(batch):
    assert batch.update([item("a", 100, 100)]) == 99
    assert batch.update([item("a", 100, 100), item("b", 10**12, 10**12)]) == 99


def test_never_above_99_with_done_member_and_full_moving(batch):
    batch.update([item("a", 1, 100), item("b", 1, 100)])
    assert batch.update([item("a", 100, 100, "done"), item("b", 100, 100)]) == 99


def test_zero_total_gives_zero(batch):
    assert batch.update([item("a", 0, 0)]) == 0


def test_zero_byte_member_with_others(batch):
    assert batch.update([item("a", 0, 0), item("b", 50, 100)]) == 50


def test_shown_is_clamped_to_total_and_zero(batch):
    assert batch.update([item("a", 500, 100), item("b", -40, 100)]) == 50


def test_unfinished_member_whose_bubble_vanishes_is_dropped(batch):
    batch.update([item("a", 50, 100), item("b", 0, 300)])
    assert batch.update([item("a", 50, 100)]) == 50


def test_clear_forgets_members(batch):
    batch.update([item("a", 100, 100, "moving"), item("b", 0, 100)])
    batch.update([item("a", 100, 100, "done"), item("b", 0, 100)])
    batch.clear()
    assert batch.update([item("b", 0, 100)]) == 0, "sau clear: lượt a DONE không còn trong đợt"


def test_new_member_mid_batch_may_lower_percent(batch):
    assert batch.update([item("a", 80, 100)]) == 80
    assert batch.update([item("a", 80, 100), item("b", 0, 300)]) == 20


# ---- S10 ----------------------------------------------------------------------------------------


def test_reconnecting_member_gives_none_but_batch_is_kept(batch):
    assert batch.update([item("a", 50, 100), item("b", 0, 100)]) == 25
    assert batch.update([item("a", 50, 100, "reconnecting"), item("b", 0, 100, "reconnecting")]) is None
    # a chạy lại, b vẫn chờ nối lại: b còn trong đợt (mẫu 200), không phải đợt mới chỉ có a.
    assert batch.update([item("a", 60, 100), item("b", 0, 100, "reconnecting")]) == 30


def test_reconnecting_member_still_counts_while_another_moves(batch):
    batch.update([item("a", 10, 100), item("b", 30, 100)])
    assert batch.update([item("a", 50, 100), item("b", 30, 100, "reconnecting")]) == 40


def test_reconnecting_member_still_counted_after_return(batch):
    batch.update([item("a", 20, 100)])
    assert batch.update([item("a", 20, 100, "reconnecting")]) is None
    assert batch.update([item("a", 70, 100)]) == 70


def test_queued_send_joins_running_batch_and_done_total_stays(batch):
    assert batch.update([item("a", 50, 100)]) == 50
    # a xong, lượt gửi kế tiếp cùng máy đang QUEUED: không thành viên nào chạy → None, nhưng b vào đợt
    # và đợt còn; b chạy thì tử vẫn tính 100 của a (S10).
    assert batch.update([item("a", 100, 100, "done"), item("b", 0, 100, "queued_send")]) is None
    assert batch.update([item("a", 100, 100, "done"), item("b", 50, 100)]) == 75


def test_queued_send_while_batch_empty_does_not_start_batch(batch):
    assert batch.update([item("b", 0, 100, "queued_send")]) is None
    assert batch.update([item("b", 0, 100, "queued_send")]) is None
    assert batch.update([item("b", 20, 100)]) == 20


@pytest.mark.parametrize("state", ["queued_receive", "waiting", "reconnecting"])
def test_non_moving_new_transfer_does_not_join_running_batch(batch, state):
    batch.update([item("a", 50, 100)])
    assert batch.update([item("a", 50, 100), item("x", 0, 300, state)]) == 50


def test_done_member_whose_bubble_vanishes_still_counts(batch):
    batch.update([item("a", 50, 100), item("b", 0, 100)])
    batch.update([item("a", 100, 100, "done"), item("b", 0, 100)])
    # Bong bóng DONE của a bị `_trim` khỏi luồng: đợt vẫn nhớ total của a.
    assert batch.update([item("b", 50, 100)]) == 75


def test_done_member_vanished_then_last_member_done_ends_batch(batch):
    batch.update([item("a", 50, 100), item("b", 0, 100)])
    batch.update([item("a", 100, 100, "done"), item("b", 0, 100)])
    assert batch.update([item("b", 100, 100, "done")]) is None
    assert batch.update([item("c", 30, 100)]) == 30


# ---- Thuộc tính --------------------------------------------------------------------------------

_items = st.lists(
    st.tuples(
        st.sampled_from("abcdef"),
        st.integers(min_value=-10, max_value=2_000),
        st.integers(min_value=0, max_value=1_000),
        st.sampled_from(STATES),
    ),
    max_size=6,
    unique_by=lambda t: t[0],
)


@settings(max_examples=300, deadline=None)
@given(st.lists(_items, min_size=1, max_size=25))
def test_property_result_is_none_or_0_to_99_and_none_iff_nothing_moves(steps):
    from teleport.ui.progress import ProgressBatch

    b = ProgressBatch()
    ended: dict[str, str] = {}  # lượt đã kết thúc thì ở nguyên trạng thái kết thúc (như bong bóng thật)
    for step in steps:
        items = []
        for k, shown, total, state in step:
            state = ended.get(k, state)
            if state in ("done", "failed"):
                ended[k] = state
            items.append(item(k, shown, total, state))
        got = b.update(items)
        moving = any(i.moving for i in items)
        if moving:
            assert isinstance(got, int) and not isinstance(got, bool)
            assert 0 <= got <= 99, (step, got)
        else:
            assert got is None, (step, got)


# =================================================================================================
# R2: quantize, ProgressThrottle
# =================================================================================================


def test_constants_are_spec_values():
    from teleport.ui import progress

    assert progress.TITLE_STEP == 5
    assert progress.TITLE_MIN_INTERVAL == 5.0


def test_quantize_rounds_down_to_step():
    from teleport.ui.progress import quantize

    assert quantize(62) == 60
    assert quantize(99) == 95
    assert quantize(0) == 0
    assert quantize(5) == 5
    assert quantize(4) == 0


def test_quantize_is_multiple_of_step_within_0_95():
    from teleport.ui.progress import quantize

    for p in range(100):
        q = quantize(p)
        assert q % 5 == 0 and 0 <= q <= min(p, 95), (p, q)


def test_quantize_reads_step_at_call_time(monkeypatch):
    from teleport.ui import progress

    monkeypatch.setattr(progress, "TITLE_STEP", 10)
    assert progress.quantize(67) == 60
    monkeypatch.setattr(progress, "TITLE_STEP", 1)
    assert progress.quantize(67) == 67


def test_first_value_applies_immediately(throttle):
    assert throttle.feed(40, 100.0) == 40
    assert throttle.pending_delay(100.0) is None


def test_first_value_is_quantized(throttle):
    assert throttle.feed(62, 0.0) == 60


def test_none_before_any_value_stays_none(throttle):
    assert throttle.feed(None, 0.0) is None
    assert throttle.pending_delay(0.0) is None


def test_end_applies_immediately(throttle):
    throttle.feed(40, 0.0)
    assert throttle.feed(None, 0.5) is None
    assert throttle.pending_delay(0.5) is None


def test_change_within_interval_is_held_with_correct_delay(throttle):
    assert throttle.feed(40, 10.0) == 40
    assert throttle.feed(62, 11.0) == 40
    assert throttle.pending_delay(11.0) == pytest.approx(4.0)
    assert throttle.pending_delay(13.5) == pytest.approx(1.5)


def test_held_change_applies_after_interval(throttle):
    throttle.feed(40, 10.0)
    throttle.feed(62, 11.0)
    assert throttle.feed(62, 15.1) == 60
    assert throttle.pending_delay(15.1) is None


def test_held_value_replaced_by_newer_target(throttle):
    throttle.feed(40, 0.0)
    throttle.feed(62, 1.0)
    throttle.feed(78, 2.0)
    assert throttle.feed(78, 5.5) == 75


def test_target_equal_to_shown_drops_held_value(throttle):
    throttle.feed(40, 0.0)
    assert throttle.feed(62, 1.0) == 40
    assert throttle.feed(43, 2.0) == 40  # quantize(43) == 40 == đang hiện
    assert throttle.pending_delay(2.0) is None


def test_quantized_same_value_is_not_a_change(throttle):
    throttle.feed(40, 0.0)
    assert throttle.feed(44, 10.0) == 40
    assert throttle.pending_delay(10.0) is None


def test_zero_to_99_in_three_seconds_changes_once_after_start(throttle):
    shown = [throttle.feed(p, p * 3.0 / 99) for p in range(100)]
    assert changes(shown) == 1, "trong 3 giây chỉ có lần bắt đầu"
    assert shown[-1] == 0
    delay = throttle.pending_delay(3.0)
    assert delay is not None and delay == pytest.approx(2.0)
    shown.append(throttle.feed(99, 3.0 + delay + 0.01))
    assert shown[-1] == 95
    assert changes(shown) == 2, "đúng một lần đổi sau lần bắt đầu"


def test_hundred_ticks_in_sixty_seconds_are_rate_limited(throttle):
    from teleport.ui import progress

    shown = []
    for i in range(100):
        now = i * 0.6
        shown.append(throttle.feed(i % 100, now))
    assert changes(shown) <= 60 / progress.TITLE_MIN_INTERVAL + 2


def test_noisy_ticks_still_rate_limited(throttle):
    from teleport.ui import progress

    shown = []
    for i in range(100):
        now = i * 0.6
        p = None if i % 7 == 3 else (i * 37) % 100  # bắt đầu/kết thúc xen kẽ, số nhảy lung tung
        shown.append(throttle.feed(p, now))
    # Mỗi lần “kết thúc” áp ngay nên trần rộng hơn, nhưng “bắt đầu” lại phải chờ khoảng tối thiểu.
    assert changes(shown) <= 2 * (60 / progress.TITLE_MIN_INTERVAL + 2)


def test_start_end_start_within_one_second_changes_at_most_twice(throttle):
    shown = [throttle.feed(40, 0.0), throttle.feed(None, 0.3), throttle.feed(40, 0.6)]
    assert changes(shown) <= 2
    assert shown[:2] == [40, None]
    assert shown[2] is None, "bắt đầu lại ngay sau một lần đổi: giữ, không áp"
    delay = throttle.pending_delay(0.6)
    assert delay is not None and delay == pytest.approx(4.7)


def test_start_after_interval_applies_immediately(throttle):
    throttle.feed(40, 0.0)
    throttle.feed(None, 0.3)
    assert throttle.feed(20, 5.4) == 20


def test_reset_forgets_shown_value(throttle):
    throttle.feed(40, 0.0)
    throttle.feed(70, 1.0)
    throttle.reset()
    assert throttle.pending_delay(1.0) is None
    assert throttle.feed(70, 1.1) == 70


def test_min_interval_read_at_call_time(monkeypatch, throttle):
    from teleport.ui import progress

    monkeypatch.setattr(progress, "TITLE_MIN_INTERVAL", 1.0)
    throttle.feed(40, 0.0)
    assert throttle.feed(62, 0.5) == 40
    assert throttle.pending_delay(0.5) == pytest.approx(0.5)
    assert throttle.feed(62, 1.1) == 60


# =================================================================================================
# S19: không kéo Qt, không import module ui khác
# =================================================================================================


def test_progress_module_imports_no_pyside6_and_no_other_ui_module():
    import teleport

    src = str(Path(teleport.__file__).resolve().parents[1])
    env = dict(os.environ)
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "import sys, teleport.ui.progress\n"
        "print(sorted(m for m in sys.modules if m.startswith('PySide6')))\n"
        "ui = [m for m in sys.modules if m.startswith('teleport.ui.') and m != 'teleport.ui.progress']\n"
        "print(sorted(ui))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    qt, ui = out.stdout.strip().splitlines()
    assert qt == "[]", f"teleport.ui.progress kéo theo PySide6: {qt}"
    assert ui == "[]", f"teleport.ui.progress import module ui khác: {ui}"
