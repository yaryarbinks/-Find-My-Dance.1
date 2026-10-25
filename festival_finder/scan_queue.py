"""Persistent folder scan queue and detached queue-worker launcher."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from festival_finder.detection_jobs import alive, write_json


def queue_path(data):
    return Path(data) / 'jobs' / 'scan-queue.json'


def read_queue(data):
    path = queue_path(data)
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'status': 'idle', 'entries': [], 'current': None}


def folder_subtree(folders, selected):
    by_id = {folder['id']: folder for folder in folders}
    if selected not in by_id:
        raise ValueError('Select a folder in the loaded festival tree first.')
    children = {}
    for folder in folders:
        children.setdefault(folder.get('parent'), []).append(folder)
    result, visited, pending = [], set(), [selected]
    while pending:
        folder_id = pending.pop()
        if folder_id in visited:
            continue
        visited.add(folder_id)
        folder = by_id.get(folder_id)
        if folder is None:
            continue
        result.append(folder)
        pending.extend(reversed([child['id'] for child in children.get(folder_id, [])]))
    return result


def add_folders(data, folders, selected, rescan=False):
    path = queue_path(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = read_queue(data)
    if state.get('status') in {'starting', 'running'}:
        raise ValueError('Wait for the running folder queue to finish before adding more folders.')
    existing = {entry['id']: entry for entry in state.get('entries', [])}
    additions = []
    for folder in folder_subtree(folders, selected):
        previous = existing.get(folder['id'])
        if previous:
            if rescan and previous.get('status') == 'completed':
                previous.update(status='pending', error='', result='')
            continue
        entry = {'id': folder['id'], 'name': folder['name'], 'path': folder['path'],
                 'status': 'pending', 'error': ''}
        additions.append(entry)
        existing[folder['id']] = entry
    state.setdefault('entries', []).extend(additions)
    pending = any(entry.get('status') in {'pending', 'failed'} for entry in state['entries'])
    state['status'] = 'queued' if pending else ('finished' if state['entries'] else 'idle')
    state['current'] = None
    write_json(path, state)
    return state


def clear_queue(data):
    state = read_queue(data)
    if state.get('status') in {'starting', 'running'}:
        raise ValueError('The running folder queue cannot be cleared.')
    state = {'status': 'idle', 'entries': [], 'current': None}
    write_json(queue_path(data), state)
    return state


def start_queue(root, data, config):
    root, data = Path(root).resolve(), Path(data).resolve()
    path = queue_path(data)
    state = queue_status(data)
    if state.get('status') in {'starting', 'running'}:
        raise ValueError('The folder queue is already running.')
    for entry in state.get('entries', []):
        if entry.get('status') == 'failed':
            entry.update(status='pending', error='')
    if not any(entry.get('status') == 'pending' for entry in state.get('entries', [])):
        raise ValueError('Add at least one folder to the queue first.')

    active = Path(data) / 'jobs' / 'launch.lock'
    if active.exists():
        raise ValueError('Another scan is starting. Wait a moment before starting the folder queue.')
    from festival_finder.jobs import current_job
    job = current_job(data)
    if job and job.get('status') in {'starting', 'running'}:
        raise ValueError('A folder scan is already running. Wait for it to finish before starting the queue.')

    lock = Path(data) / 'jobs' / 'queue-launch.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError('The folder queue is already starting.') from exc
    os.close(descriptor)
    try:
        config_path = Path(data) / 'jobs' / 'scan-queue-config.json'
        write_json(config_path, {**config, 'root': str(root), 'data': str(data),
                                 'force': bool(config.get('force'))})
        state.update(status='starting', current=None,
                     started=datetime.now(timezone.utc).isoformat(), error='', worker_pid=None)
        write_json(path, state)
        executable = Path(sys.executable)
        options = {'cwd': str(root), 'stdin': subprocess.DEVNULL, 'close_fds': True}
        if os.name == 'nt':
            executable = executable.with_name('pythonw.exe')
            options['creationflags'] = subprocess.CREATE_NO_WINDOW
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            options['startupinfo'] = startup
        else:
            options['start_new_session'] = True
        try:
            with (Path(data) / 'jobs' / 'scan-queue.log').open('ab') as output:
                process = subprocess.Popen([str(executable), '-m', 'festival_finder.queue_worker',
                                            str(config_path)], stdout=output, stderr=subprocess.STDOUT, **options)
        except OSError as exc:
            state.update(status='failed', error=f'Could not start the folder queue: {exc}')
            write_json(path, state)
            raise
        state = read_queue(data)
        state['worker_pid'] = process.pid
        if state.get('status') == 'starting':
            state['status'] = 'running'
        write_json(path, state)
        return state
    finally:
        lock.unlink(missing_ok=True)


def queue_status(data):
    state = read_queue(data)
    if state.get('status') in {'starting', 'running'}:
        pid = state.get('worker_pid')
        try:
            startup_age = (datetime.now(timezone.utc) -
                           datetime.fromisoformat(state['started'])).total_seconds()
        except (KeyError, ValueError):
            startup_age = 16
        worker_alive = alive(pid) if pid else startup_age < 15
        if not worker_alive:
            state.update(status='interrupted',
                         error='The folder queue stopped unexpectedly. Pending folders remain saved.')
            for entry in state.get('entries', []):
                if entry.get('status') == 'running':
                    entry.update(status='pending', error='')
            state['current'] = None
            write_json(queue_path(data), state)
    return state
