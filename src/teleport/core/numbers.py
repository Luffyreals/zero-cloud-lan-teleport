"""Kiểm số dùng chung của `core` (sans-IO)."""

from __future__ import annotations

import math


def is_finite(value: int | float) -> bool:
    """`value` hữu hạn và đổi được sang float.

    Số nguyên quá lớn cho float → False: `math.isfinite` ném OverflowError với số như vậy,
    nên các hàm kiểm tham số dùng hàm này để trả đúng ValueError đã hứa.
    """
    try:
        return math.isfinite(value)
    except OverflowError:
        return False
