"""Test `teleport.core.keepalive` theo đặc tả PR-2 mục 2.2 và 4.2 (K1–K10).

Keepalive tính theo byte (protocol.md §2.3): không gửi gì trong `ping_interval` → gửi `ping`;
không nhận byte nào trong `dead_after` → mất kết nối. Module sans-IO: bên gọi đưa `now`.
"""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from teleport.core.keepalive import DEAD_AFTER, PING_INTERVAL, Keepalive, KeepaliveAction

T0 = 1000.0


# --- K1: hằng số ---------------------------------------------------------------------------------


def test_constants_match_protocol():
    assert PING_INTERVAL == 10.0
    assert DEAD_AFTER == 30.0


def test_action_values():
    assert {a.value for a in KeepaliveAction} == {"none", "send_ping", "dead"}
    assert KeepaliveAction.SEND_PING == "send_ping"


# --- K2–K7: ngữ nghĩa ----------------------------------------------------------------------------


def test_fresh_keepalive_is_idle_and_wakes_at_ping_interval():
    k = Keepalive(T0)
    assert k.poll(T0) is KeepaliveAction.NONE
    assert k.dead is False
    assert k.next_wakeup() == T0 + 10


def test_ping_due_exactly_at_interval_and_not_repeated():
    k = Keepalive(T0)
    assert k.poll(T0 + 9.999) is KeepaliveAction.NONE
    assert k.poll(T0 + 10) is KeepaliveAction.SEND_PING
    # poll đã đặt last_sent = now: gọi lại ngay không được gửi ping trùng.
    assert k.poll(T0 + 10) is KeepaliveAction.NONE
    assert k.next_wakeup() == T0 + 20


def test_sending_data_postpones_ping():
    k = Keepalive(T0)
    k.sent(T0 + 5)
    assert k.poll(T0 + 10) is KeepaliveAction.NONE
    assert k.next_wakeup() == T0 + 15
    assert k.poll(T0 + 15) is KeepaliveAction.SEND_PING


def test_receiving_does_not_postpone_ping():
    """Ping do việc *gửi* quyết định; nhận dữ liệu chỉ lùi mốc chết."""
    k = Keepalive(T0)
    k.received(T0 + 5)
    assert k.poll(T0 + 10) is KeepaliveAction.SEND_PING


def test_dead_after_silence_with_pings_on_the_way():
    k = Keepalive(T0)
    assert k.poll(T0 + 10) is KeepaliveAction.SEND_PING
    assert k.poll(T0 + 20) is KeepaliveAction.SEND_PING
    assert k.poll(T0 + 29.999) is KeepaliveAction.NONE
    assert k.poll(T0 + 30) is KeepaliveAction.DEAD
    assert k.dead is True


def test_receiving_postpones_death():
    k = Keepalive(T0)
    assert k.poll(T0 + 10) is KeepaliveAction.SEND_PING
    assert k.poll(T0 + 20) is KeepaliveAction.SEND_PING
    k.received(T0 + 29)
    assert k.poll(T0 + 30) is not KeepaliveAction.DEAD
    assert k.dead is False
    assert k.poll(T0 + 58.999) is not KeepaliveAction.DEAD
    assert k.poll(T0 + 59) is KeepaliveAction.DEAD


def test_dead_is_sticky():
    k = Keepalive(T0)
    assert k.poll(T0 + 30) is KeepaliveAction.DEAD
    k.received(T0 + 31)
    k.sent(T0 + 31)
    assert k.poll(T0 + 31) is KeepaliveAction.DEAD
    assert k.poll(T0 + 1000) is KeepaliveAction.DEAD
    assert k.dead is True
    assert k.next_wakeup() == math.inf


def test_dead_takes_priority_over_ping_on_first_late_poll():
    k = Keepalive(T0)
    assert k.poll(T0 + 31) is KeepaliveAction.DEAD
    assert k.dead is True


def test_next_wakeup_is_min_of_ping_and_dead_deadlines():
    k = Keepalive(T0, ping_interval=2.0, dead_after=5.0)
    k.sent(T0 + 4)
    # last_sent + 2 = T0+6 > last_received + 5 = T0+5
    assert k.next_wakeup() == T0 + 5
    k.received(T0 + 4)
    assert k.next_wakeup() == T0 + 6


def test_custom_intervals_are_used():
    k = Keepalive(0.0, ping_interval=0.2, dead_after=0.6)
    assert k.next_wakeup() == pytest.approx(0.2)
    assert k.poll(0.2) is KeepaliveAction.SEND_PING
    assert k.poll(0.6) is KeepaliveAction.DEAD


def test_int_now_is_accepted():
    k = Keepalive(0)
    k.sent(1)
    k.received(2)
    assert k.poll(3) is KeepaliveAction.NONE


# --- K8: kiểm `now` --------------------------------------------------------------------------------


METHODS = ["sent", "received", "poll"]


@pytest.mark.parametrize("bad_now", [True, False, "1", None, b"1"], ids=repr)
def test_constructor_rejects_non_number_now(bad_now):
    with pytest.raises(TypeError):
        Keepalive(bad_now)


@pytest.mark.parametrize("bad_now", [math.nan, math.inf, -math.inf, 10**400, -(10**400)])
def test_constructor_rejects_non_finite_now(bad_now):
    with pytest.raises(ValueError):
        Keepalive(bad_now)


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("bad_now", [True, False, "1", None, b"1"], ids=repr)
def test_methods_reject_non_number_now(method, bad_now):
    k = Keepalive(T0)
    with pytest.raises(TypeError):
        getattr(k, method)(bad_now)


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("bad_now", [math.nan, math.inf, -math.inf, 10**400, -(10**400)])
def test_methods_reject_non_finite_now(method, bad_now):
    k = Keepalive(T0)
    with pytest.raises(ValueError):
        getattr(k, method)(bad_now)


@pytest.mark.parametrize("method", METHODS)
def test_methods_reject_now_before_construction(method):
    k = Keepalive(T0)
    with pytest.raises(ValueError):
        getattr(k, method)(T0 - 0.001)


@pytest.mark.parametrize("first", METHODS)
@pytest.mark.parametrize("second", METHODS)
def test_now_must_not_go_backwards_across_methods(first, second):
    """Kiểm thứ tự thời gian áp chung cho mọi phương thức của cùng đối tượng."""
    k = Keepalive(T0)
    getattr(k, first)(T0 + 5)
    with pytest.raises(ValueError):
        getattr(k, second)(T0 + 4.999)


def test_same_now_twice_is_allowed():
    k = Keepalive(T0)
    k.sent(T0)
    k.received(T0)
    assert k.poll(T0) is KeepaliveAction.NONE


# --- K9: kiểm tham số ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ping_interval", "dead_after"),
    [
        (0, 30.0),
        (0.0, 30.0),
        (-1.0, 30.0),
        (10.0, 10.0),
        (10.0, 5.0),
        (10.0, 0.0),
        (10.0, -1.0),
        (math.nan, 30.0),
        (10.0, math.nan),
        (math.inf, 30.0),
        (10.0, math.inf),
        (-math.inf, 30.0),
    ],
    ids=repr,
)
def test_rejects_bad_intervals(ping_interval, dead_after):
    with pytest.raises(ValueError):
        Keepalive(T0, ping_interval=ping_interval, dead_after=dead_after)


@pytest.mark.parametrize(
    ("ping_interval", "dead_after"), [(True, 30.0), (10.0, True), (False, 30.0)], ids=repr
)
def test_rejects_bool_intervals(ping_interval, dead_after):
    with pytest.raises((TypeError, ValueError)):
        Keepalive(T0, ping_interval=ping_interval, dead_after=dead_after)


@pytest.mark.parametrize(("ping_interval", "dead_after"), [("10", 30.0), (10.0, None)], ids=repr)
def test_rejects_non_number_intervals(ping_interval, dead_after):
    with pytest.raises(TypeError):
        Keepalive(T0, ping_interval=ping_interval, dead_after=dead_after)


def test_int_intervals_are_accepted():
    k = Keepalive(0, ping_interval=1, dead_after=3)
    assert k.poll(1) is KeepaliveAction.SEND_PING


# --- K10: property test với mô hình tham chiếu ---------------------------------------------------

# Thời gian là bội của 0.25 để phép cộng/trừ số thực là chính xác: mô hình và cài đặt không
# lệch nhau ở biên chỉ vì làm tròn (a - b >= c và a >= b + c cho cùng kết quả).
quarter = st.integers(min_value=0, max_value=60).map(lambda n: n * 0.25)
ops = st.lists(st.tuples(st.sampled_from(["sent", "received", "poll"]), quarter), max_size=60)
intervals = st.integers(min_value=1, max_value=20).flatmap(
    lambda pi: st.tuples(
        st.just(pi * 0.25), st.integers(min_value=pi + 1, max_value=80).map(lambda d: d * 0.25)
    )
)


@pytest.mark.slow
@settings(max_examples=400, deadline=None)
@given(t0=st.integers(min_value=-1000, max_value=1000).map(float), params=intervals, steps=ops)
def test_property_keepalive_matches_reference_model(t0, params, steps):
    pi, da = params
    k = Keepalive(t0, ping_interval=pi, dead_after=da)
    now = t0
    last_sent = last_received = t0
    dead = False
    for op, dt in steps:
        now += dt
        if op == "sent":
            k.sent(now)
            if not dead:
                last_sent = now
        elif op == "received":
            k.received(now)
            if not dead:
                last_received = now
        else:
            action = k.poll(now)
            # (a) DEAD ⇔ đã dead, hoặc im lặng đủ dead_after.
            expect_dead = dead or now - last_received >= da
            assert (action is KeepaliveAction.DEAD) == expect_dead
            if expect_dead:
                dead = True
            elif now - last_sent >= pi:
                assert action is KeepaliveAction.SEND_PING
                last_sent = now
            else:
                # (c) SEND_PING chỉ khi đến hạn.
                assert action is KeepaliveAction.NONE
            if not dead:
                # (b) sau một poll không DEAD, lần thức kế tiếp nằm sau `now`.
                assert k.next_wakeup() > now
        assert k.dead is dead
        if dead:
            assert k.next_wakeup() == math.inf
        else:
            assert k.next_wakeup() == min(last_sent + pi, last_received + da)
