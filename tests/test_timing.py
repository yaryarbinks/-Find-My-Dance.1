from datetime import datetime, timezone

import pytest

from festival_finder.timing import ScanTiming, duration_text


def test_eta_warmup_progress_and_finish():
    now = [0.]
    timer = ScanTiming(10, lambda: now[0])
    wall = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
    assert timer.snapshot(wall)['remaining_seconds'] is None
    for _ in range(5):
        now[0] += 2
        timer.complete_file()
    result = timer.snapshot(wall)
    assert result['elapsed_seconds'] == 10
    assert result['remaining_seconds'] == 10
    assert result['estimated_finish'] == '2026-10-22T12:00:10+00:00'
    for _ in range(5):
        now[0] += 3
        timer.complete_file()
    assert timer.snapshot(wall)['remaining_seconds'] == 0


def test_eta_uses_recent_speed_and_handles_empty_scan():
    now = [0.]
    timer = ScanTiming(30, lambda: now[0])
    for i in range(25):
        now[0] += 100 if i < 5 else 1
        timer.complete_file()
    wall = datetime.now(timezone.utc)
    assert timer.snapshot(wall)['remaining_seconds'] == pytest.approx(5)
    assert ScanTiming(0).snapshot(wall)['remaining_seconds'] == 0
    assert duration_text(None) == 'Estimating…'
    assert duration_text(65) == '1m 5s'
    assert duration_text(3665) == '1h 1m'
