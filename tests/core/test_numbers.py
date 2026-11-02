"""Kiểm số dùng chung (`teleport.core.numbers`) và các hàm kiểm tham số dùng nó."""

from __future__ import annotations

import math

import pytest

from teleport.core.admission import AdmissionGate
from teleport.core.display import format_duration
from teleport.core.numbers import is_finite


@pytest.mark.parametrize("value", [0, -1, 1.5, 10**300, -(10**300), 1e308])
def test_is_finite_true(value):
    assert is_finite(value) is True


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, 10**400, -(10**400)])
def test_is_finite_false(value):
    assert is_finite(value) is False


@pytest.mark.parametrize(
    "call",
    [
        lambda: AdmissionGate().admit("192.168.1.5", 10**400),
        lambda: format_duration(10**400),
    ],
    ids=["admission", "display"],
)
def test_huge_int_is_value_error_not_overflow(call):
    """Số nguyên quá lớn cho float là “không hữu hạn”: ValueError như docstring hứa, không OverflowError."""
    with pytest.raises(ValueError):
        call()
