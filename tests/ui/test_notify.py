"""`teleport.ui.notify`: gộp thông báo nhận xong (spec-f4 mục 2.5; mục 8 S5, S12 thắng khi khác). Tiêu
chí R8.

Viết từ spec, không từ code. `ReceivedBatch` thuần, nhận `now` giả. Cả module gắn `real_notify_delay`:
fixture autouse `notify_immediate` (tests/ui/conftest.py) không đặt hằng về 0, để kiểm giá trị thật của
`NOTIFY_QUIET`/`NOTIFY_MAX_WAIT`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_notify_delay

A_ID = "a71c04d2" + "e" * 24
B_ID = "0f0f0f0f" + "1" * 24
ROOT = Path("C:/nhan") if sys.platform == "win32" else Path("/nhan")


@pytest.fixture
def batch():
    from teleport.ui.notify import ReceivedBatch

    return ReceivedBatch()


def add(batch, now: float, *, device_id=A_ID, peer="PC-Nha", files=1, paths=(), single=None, root=ROOT):
    batch.add(
        device_id=device_id,
        peer=peer,
        file_count=files,
        saved_paths=list(paths),
        single_name=single,
        root=root,
        now=now,
    )


def text(batch) -> str:
    from teleport.ui.notify import received_batch_text

    summary = batch.take()
    assert summary is not None
    return received_batch_text(summary)


# =================================================================================================
# Hằng, due
# =================================================================================================


def test_constants_are_spec_values():
    from teleport.ui import notify

    assert notify.NOTIFY_QUIET == 3.0
    assert notify.NOTIFY_MAX_WAIT == 10.0


def test_empty_batch_has_no_due_and_nothing_to_take(batch):
    assert len(batch) == 0
    assert batch.due(0.0) is None
    assert batch.take() is None


def test_due_after_one_add_is_quiet_time(batch):
    add(batch, 100.0)
    assert batch.due(100.0) == pytest.approx(3.0)
    assert batch.due(101.0) == pytest.approx(2.0)


def test_each_add_restarts_quiet_time(batch):
    add(batch, 0.0)
    add(batch, 2.0)
    assert batch.due(2.0) == pytest.approx(3.0)


def test_due_never_past_max_wait_from_first(batch):
    for t in (0.0, 2.5, 5.0, 7.5):
        add(batch, t)
    assert batch.due(7.5) == pytest.approx(2.5), "min(7.5 + 3, 0 + 10) - 7.5"
    add(batch, 9.9)
    assert batch.due(9.9) == pytest.approx(0.1)


def test_due_is_clamped_to_zero(batch):
    add(batch, 0.0)
    assert batch.due(50.0) == 0


def test_due_reads_constants_at_call_time(batch, monkeypatch):
    from teleport.ui import notify

    add(batch, 0.0)
    monkeypatch.setattr(notify, "NOTIFY_QUIET", 0.5)
    monkeypatch.setattr(notify, "NOTIFY_MAX_WAIT", 0.25)
    assert batch.due(0.0) == pytest.approx(0.25)
    monkeypatch.setattr(notify, "NOTIFY_QUIET", 0)
    monkeypatch.setattr(notify, "NOTIFY_MAX_WAIT", 0)
    assert batch.due(0.0) == 0


def test_len_counts_transfers(batch):
    add(batch, 0.0, files=3)
    add(batch, 1.0, device_id=B_ID, peer="Laptop-Minh", files=2)
    assert len(batch) == 2


def test_take_returns_summary_and_clears(batch):
    add(batch, 0.0)
    assert batch.take() is not None
    assert len(batch) == 0
    assert batch.take() is None
    assert batch.due(0.0) is None


def test_clear_drops_everything(batch):
    add(batch, 0.0)
    batch.clear()
    assert len(batch) == 0 and batch.take() is None


def test_after_take_next_group_starts_fresh(batch):
    add(batch, 0.0, single="a.txt")
    add(batch, 1.0, device_id=B_ID, peer="Laptop-Minh")
    batch.take()
    add(batch, 20.0, single="b.txt")
    assert batch.due(20.0) == pytest.approx(3.0), "nhóm mới tính MAX_WAIT từ lượt đầu của nó"
    assert text(batch) == "Đã nhận b.txt từ PC-Nha."


# =================================================================================================
# received_batch_text
# =================================================================================================


def test_one_transfer_one_file_names_the_saved_file(batch):
    add(batch, 0.0, files=1, single="a (1).txt", paths=[ROOT / "a (1).txt"])
    assert text(batch) == "Đã nhận a (1).txt từ PC-Nha."


def test_one_transfer_one_file_name_goes_through_file_label(batch):
    from teleport.ui import texts

    hostile = "x\u202etxt.exe"
    add(batch, 0.0, files=1, single=hostile)
    assert text(batch) == f"Đã nhận {texts.file_label(hostile)} từ PC-Nha."


def test_one_transfer_one_file_without_name_uses_count(batch):
    add(batch, 0.0, files=1, single=None)
    assert text(batch) == "Đã nhận 1 file từ PC-Nha."


def test_one_transfer_many_files_uses_count(batch):
    add(batch, 0.0, files=3)
    assert text(batch) == "Đã nhận 3 file từ PC-Nha."


def test_two_transfers_same_device_sum_files(batch):
    add(batch, 0.0, files=1, single="a.txt")
    add(batch, 1.0, files=2)
    assert text(batch) == "Đã nhận 3 file từ PC-Nha."


def test_two_single_file_transfers_same_device_use_count_not_name(batch):
    add(batch, 0.0, files=1, single="a.txt")
    add(batch, 1.0, files=1, single="b.txt")
    assert text(batch) == "Đã nhận 2 file từ PC-Nha."


def test_two_devices_use_device_count(batch):
    add(batch, 0.0, files=1, single="a.txt")
    add(batch, 1.0, device_id=B_ID, peer="Laptop-Minh", files=3)
    assert text(batch) == "Đã nhận 4 file từ 2 máy."


def test_same_device_uses_latest_name(batch):
    add(batch, 0.0, peer="PC-Cu", files=1)
    add(batch, 1.0, peer="PC-Nha", files=1)
    assert text(batch) == "Đã nhận 2 file từ PC-Nha."


def test_same_name_different_devices_count_as_two(batch):
    add(batch, 0.0, peer="PC", files=1)
    add(batch, 1.0, device_id=B_ID, peer="PC", files=1)
    assert text(batch) == "Đã nhận 2 file từ 2 máy."


def test_two_devices_text_in_english(batch, qapp):
    from teleport.ui import i18n

    i18n.set_language("en")
    add(batch, 0.0, files=1)
    add(batch, 1.0, device_id=B_ID, peer="Laptop-Minh", files=3)
    assert text(batch) == "Received 4 files from 2 devices."


# =================================================================================================
# paths, batch_reveal
# =================================================================================================


def reveal_of(batch):
    from teleport.ui.notify import batch_reveal

    summary = batch.take()
    assert summary is not None
    return batch_reveal(summary)


def test_reveal_has_saved_paths_and_root_of_last_transfer(batch):
    other = ROOT.parent / "khac"
    a, b, c = ROOT / "a.txt", other / "b.txt", other / "c.txt"
    add(batch, 0.0, paths=[a], root=ROOT)
    add(batch, 1.0, files=2, paths=[b, c], root=other)
    r = reveal_of(batch)
    assert tuple(r.files) == (a, b, c)
    assert r.root == other


def test_paths_are_capped_keeping_last(batch):
    from teleport.ui import shell

    cap = shell.REVEAL_MAX_ITEMS
    paths = [ROOT / f"f{i}.bin" for i in range(cap + 9)]
    add(batch, 0.0, files=20, paths=paths[:20])
    add(batch, 1.0, files=len(paths) - 20, paths=paths[20:])
    r = reveal_of(batch)
    assert tuple(r.files) == tuple(paths[-cap:])


def test_paths_cap_read_at_call_time(batch, monkeypatch):
    from teleport.ui import shell

    monkeypatch.setattr(shell, "REVEAL_MAX_ITEMS", 3)
    paths = [ROOT / f"f{i}.bin" for i in range(5)]
    add(batch, 0.0, files=5, paths=paths)
    assert tuple(reveal_of(batch).files) == tuple(paths[-3:])


def test_reveal_without_paths_opens_root(batch):
    add(batch, 0.0, paths=[], root=ROOT)
    r = reveal_of(batch)
    assert tuple(r.files) == ()
    assert r.root == ROOT
    assert r.folder == ROOT


def test_reveal_is_none_without_paths_and_root(batch):
    """S12: không có gì để mở → `None` (bấm bóng thoại thì đưa cửa sổ lên)."""
    add(batch, 0.0, paths=[], root=None)
    assert reveal_of(batch) is None


def test_reveal_is_shell_reveal(batch):
    from teleport.ui.shell import Reveal

    add(batch, 0.0, paths=[ROOT / "a.txt"])
    assert isinstance(reveal_of(batch), Reveal)
