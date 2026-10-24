import json
import os
import time
from pathlib import Path
import hashlib

import numpy as np

from festival_finder.engine import cache_key, save_report
from festival_finder.feedback import Feedback
from festival_finder.jobs import start_job, current_job, process_alive


def test_detached_worker_finishes_cached_scan_without_browser(tmp_path, monkeypatch):
    from festival_finder import jobs
    import subprocess
    from unittest.mock import Mock
    original_popen = subprocess.Popen
    launched = Mock(side_effect=original_popen)
    monkeypatch.setattr(jobs.subprocess, 'Popen', launched)
    data = tmp_path / 'data'
    Feedback(data / 'feedback.sqlite3')
    refs = np.eye(1, 128, dtype=np.float32)
    negatives = np.empty((0, 128), dtype=np.float32)
    items = [{'id': f'file-{i}', 'name': f'{i}.jpg', 'folder': 'Camera', 'size': 1,
              'modifiedTime': '1', 'mimeType': 'image/jpeg'} for i in range(3)]
    for item in items:
        identity = {key: item.get(key) for key in ['id', 'size', 'modifiedTime']}
        identity.update(mode='drive-preview', negative_examples=hashlib.sha256(negatives.tobytes()).hexdigest())
        key = cache_key(identity, refs, .4, 1.)
        save_report(data / 'runs' / key / 'result.json', {'hits': []})
    config = {'items': items, 'references': refs.tolist(), 'negatives': [], 'threshold': .4,
              'interval': 1., 'source': 'drive', 'folder_name': 'Camera', 'force': False}
    state = start_job(Path(__file__).resolve().parents[1], data, config)
    assert state['status'] in {'starting', 'running', 'finished'}
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = current_job(data)
        if state['status'] not in {'starting', 'running'}:
            break
        time.sleep(.1)
    assert state['status'] == 'finished', state
    report = json.loads((data / 'last-report.json').read_text())
    assert report['finished'] and report['processed'] == 3 and report['cached'] == 3
    assert not report['errors']
    assert report['worker_pid'] != os.getpid()
    if os.name == 'nt':
        assert Path(launched.call_args.args[0][0]).name == 'pythonw.exe'
        assert launched.call_args.kwargs['creationflags'] & subprocess.CREATE_NO_WINDOW
        assert not launched.call_args.kwargs['creationflags'] & subprocess.DETACHED_PROCESS
        assert launched.call_args.kwargs['startupinfo'].wShowWindow == subprocess.SW_HIDE


def test_process_liveness_and_dead_job_detection(tmp_path):
    assert process_alive(os.getpid())
    assert not process_alive(None)
    assert not process_alive(4294967294)
    directory = tmp_path / 'jobs' / 'dead'
    directory.mkdir(parents=True)
    save_report(tmp_path / 'jobs' / 'active.json', {'directory': str(directory)})
    save_report(directory / 'state.json', {'status': 'running', 'pid': 4294967294,
                                         'started': '2026-01-01T00:00:00+00:00'})
    assert current_job(tmp_path)['status'] == 'interrupted'
