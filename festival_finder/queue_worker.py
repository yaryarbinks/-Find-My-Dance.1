"""Process queued folders sequentially without depending on an open browser."""
import json
import os
import sys
import time
from pathlib import Path

from festival_finder import drive
from festival_finder.detection_jobs import write_json
from festival_finder.jobs import current_job, start_job
from festival_finder.projects import Projects
from festival_finder.scan_queue import queue_path, read_queue


def run(config_path):
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding='utf-8'))
    root, data = Path(config['root']), Path(config['data'])
    path = queue_path(data)
    state = read_queue(data)
    state.update(status='running', worker_pid=os.getpid(), error='')
    write_json(path, state)
    try:
        service = drive.connect(root / 'credentials.json', data / 'token.json')
        projects = Projects(data / 'feedback.sqlite3')
        while True:
            state = read_queue(data)
            entry = next((item for item in state['entries'] if item.get('status') == 'pending'), None)
            if entry is None:
                state.update(status='finished', current=None, worker_pid=None)
                write_json(path, state)
                return
            entry.update(status='running', error='')
            state.update(status='running', current=entry['id'])
            write_json(path, state)
            try:
                saved = projects.report(config['festival_id'], entry['id'])
                if (saved and saved.get('mode') != 'face_detection_only' and saved.get('finished')
                        and not saved.get('errors') and not config.get('force')):
                    entry.update(status='completed', result='Already scanned; keeping saved results.')
                    continue
                items = drive.folder_media(service, entry['id'], entry['path'])
                if not items:
                    entry.update(status='completed', result='No photos or videos in this folder.')
                    continue
                job_config = {
                    'items': items,
                    'references': config['references'],
                    'negatives': config['negatives'],
                    'threshold': config['threshold'],
                    'interval': config.get('interval', 1.0),
                    'source': 'drive',
                    'folder_name': entry['path'],
                    'festival_id': config['festival_id'],
                    'folder_id': entry['id'],
                    'force': bool(config.get('force')),
                }
                job = start_job(root, data, job_config)
                while job and job.get('status') in {'starting', 'running'}:
                    time.sleep(1)
                    job = current_job(data)
                if not job or job.get('status') != 'finished':
                    raise RuntimeError((job or {}).get('error', 'The folder scan stopped unexpectedly.'))
                errors = job.get('errors', 0)
                entry.update(status='completed',
                             result=f'{errors} file error(s); review the saved report.' if errors else '')
            except Exception as exc:
                entry.update(status='failed', error=str(exc))
            finally:
                state = read_queue(data)
                saved_entry = next(item for item in state['entries'] if item['id'] == entry['id'])
                saved_entry.update({key: value for key, value in entry.items()
                                    if key in {'status', 'error', 'result'}})
                state['current'] = None
                write_json(path, state)
    except Exception as exc:
        state = read_queue(data)
        state.update(status='failed', current=None, worker_pid=None, error=str(exc))
        for entry in state.get('entries', []):
            if entry.get('status') == 'running':
                entry.update(status='failed', error=str(exc))
        write_json(path, state)


if __name__ == '__main__':
    run(sys.argv[1])
