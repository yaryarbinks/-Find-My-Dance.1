"""Estimate scan completion from a rolling window of completed files."""
from collections import deque
from datetime import timedelta
import math
import time


def duration_text(seconds):
    if seconds is None:
        return 'Estimating…'
    minutes, seconds = divmod(max(0, math.ceil(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours}h {minutes}m'
    return f'{minutes}m {seconds}s'


class ScanTiming:
    def __init__(self, total, clock=time.monotonic):
        self.total = total
        self.clock = clock
        self.started = self.last = clock()
        self.samples = deque(maxlen=20)
        self.completed = 0

    def complete_file(self):
        now = self.clock()
        self.samples.append(max(0, now - self.last))
        self.last = now
        self.completed += 1

    def snapshot(self, wall_time):
        elapsed = max(0, self.clock() - self.started)
        remaining = max(0, self.total - self.completed)
        estimate = 0 if not remaining else (
            sum(self.samples) / len(self.samples) * remaining if self.completed >= 5 else None)
        return {'completed': self.completed, 'total': self.total, 'elapsed_seconds': elapsed,
                'remaining_seconds': estimate,
                'estimated_finish': (wall_time + timedelta(seconds=estimate)).isoformat() if estimate is not None else None}
