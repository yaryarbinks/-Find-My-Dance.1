from festival_finder.detection_jobs import write_json
from festival_finder import queue_worker
from festival_finder.scan_queue import add_folders, clear_queue, queue_path, queue_status, read_queue


def test_add_folder_includes_descendants_and_deduplicates(tmp_path):
    folders = [
        {'id': 'festival', 'parent': None, 'name': 'Festival', 'path': 'Festival'},
        {'id': 'day-one', 'parent': 'festival', 'name': 'Day 1', 'path': 'Festival / Day 1'},
        {'id': 'camera-a', 'parent': 'day-one', 'name': 'Camera A', 'path': 'Festival / Day 1 / Camera A'},
        {'id': 'camera-b', 'parent': 'day-one', 'name': 'Camera B', 'path': 'Festival / Day 1 / Camera B'},
        {'id': 'day-two', 'parent': 'festival', 'name': 'Day 2', 'path': 'Festival / Day 2'},
    ]

    state = add_folders(tmp_path, folders, 'day-one')
    assert [entry['id'] for entry in state['entries']] == ['day-one', 'camera-a', 'camera-b']
    assert all(entry['status'] == 'pending' for entry in state['entries'])

    state = add_folders(tmp_path, folders, 'camera-a')
    assert [entry['id'] for entry in state['entries']] == ['day-one', 'camera-a', 'camera-b']

    state = add_folders(tmp_path, folders, 'day-two')
    assert [entry['id'] for entry in state['entries']] == ['day-one', 'camera-a', 'camera-b', 'day-two']
    assert clear_queue(tmp_path) == {'status': 'idle', 'entries': [], 'current': None}


def test_queue_worker_scans_folders_in_order_and_includes_video_previews(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    jobs = data / 'jobs'
    jobs.mkdir(parents=True)
    write_json(queue_path(data), {
        'status': 'starting', 'current': None,
        'entries': [
            {'id': 'first', 'name': 'First', 'path': 'Festival / First', 'status': 'pending'},
            {'id': 'second', 'name': 'Second', 'path': 'Festival / Second', 'status': 'pending'},
        ],
    })
    config_path = jobs / 'scan-queue-config.json'
    write_json(config_path, {
        'root': str(tmp_path), 'data': str(data), 'festival_id': 'festival',
        'references': [[0.0] * 128], 'negatives': [], 'threshold': 0.4, 'interval': 1.0,
    })
    video = {'id': 'clip', 'name': 'clip.mp4', 'mimeType': 'video/mp4'}
    photo = {'id': 'still', 'name': 'still.jpg', 'mimeType': 'image/jpeg'}
    monkeypatch.setattr(queue_worker.drive, 'connect', lambda *args: object())
    monkeypatch.setattr(queue_worker.drive, 'folder_media', lambda service, folder, path: [video, photo])

    class SavedProjects:
        def __init__(self, path):
            pass

        def report(self, festival, folder):
            return None

    monkeypatch.setattr(queue_worker, 'Projects', SavedProjects)
    scanned = []

    def start_job(root, data, config):
        scanned.append((config['folder_id'], config['items']))
        return {'status': 'finished'}

    monkeypatch.setattr(queue_worker, 'start_job', start_job)

    queue_worker.run(config_path)

    state = read_queue(data)
    assert state['status'] == 'finished'
    assert [entry['status'] for entry in state['entries']] == ['completed', 'completed']
    assert [folder for folder, _ in scanned] == ['first', 'second']
    assert all(items == [video, photo] for _, items in scanned)


def test_dead_queue_worker_preserves_pending_folders_for_resume(tmp_path):
    write_json(queue_path(tmp_path), {
        'status': 'running', 'started': '2026-01-01T00:00:00+00:00', 'worker_pid': 4294967294,
        'current': 'folder',
        'entries': [{'id': 'folder', 'name': 'Folder', 'path': 'Festival / Folder', 'status': 'running'}],
    })

    state = queue_status(tmp_path)

    assert state['status'] == 'interrupted'
    assert state['entries'][0]['status'] == 'pending'
    assert state['current'] is None
