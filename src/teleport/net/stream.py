"""Đọc/ghi message điều khiển trên một kết nối asyncio (khung định nghĩa ở `teleport.core.framing`)."""

from __future__ import annotations

import asyncio

from teleport.core.framing import (
    HEADER,
    MAX_MESSAGE_SIZE,
    FramingError,
    decode_body,
    decode_header,
    encode_message,
)


async def read_message(reader: asyncio.StreamReader, max_size: int = MAX_MESSAGE_SIZE) -> dict | None:
    """Đọc một message dài tối đa `max_size` byte (header lớn hơn → FramingError, không đọc thân).

    Trả về None nếu bên kia đóng kết nối đúng ở ranh giới giữa hai message
    (đóng gọn gàng). Đóng giữa chừng một message thì raise FramingError.
    Không tự đặt timeout: bên gọi bọc trong `asyncio.timeout` (protocol.md mục 2).
    """
    try:
        header = await reader.readexactly(HEADER.size)
    except asyncio.IncompleteReadError as e:
        if not e.partial:
            return None
        raise FramingError("kết nối bị cắt giữa header") from e

    length = decode_header(header, max_size)
    try:
        body = await reader.readexactly(length)
    except asyncio.IncompleteReadError as e:
        raise FramingError(f"kết nối bị cắt: mới nhận {len(e.partial)}/{length} byte") from e
    return decode_body(body)


async def write_message(writer: asyncio.StreamWriter, msg: dict) -> None:
    """Ghi một message rồi `drain()`.

    Không tự đặt thời gian chờ: bên gọi bọc trong `asyncio.timeout` (`DRAIN_TIMEOUT`,
    protocol.md mục 2.3), nếu không máy kia không đọc thì bên gửi treo mãi.
    """
    writer.write(encode_message(msg))
    # drain() chờ khi bộ đệm gửi vượt ngưỡng: đây là backpressure ở mức nhỏ nhất.
    await writer.drain()
