"""Detached scan jobs: browser navigation cannot cancel recognition."""
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from festival_finder.engine import save_report


def process_alive(pid):
    if not pid:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, OverflowError):
        return False


def current_job(data):
    pointer = Path(data) / 'jobs' / 'active.json'
    if not pointer.exists():
        return None
    try:
        job_dir = Path(json.loads(pointer.read_text())['directory'])
        state = json.loads((job_dir / 'state.json').read_text())
        pid_file = job_dir / 'pid.txt'
        # A Windows venv launcher can have a different PID from the Python worker.
        pid = state.get('pid') or (int(pid_file.read_text()) if pid_file.exists() else None)
        state.update(directory=str(job_dir), pid=pid)
        if state['status'] in {'starting', 'running'}:
            startup_age = (datetime.now(timezone.utc) - datetime.fromisoformat(state['started'])).total_seconds()
            alive = process_alive(pid) if pid else startup_age < 15
            if not alive:
                state['status'] = 'interrupted'
                state['error'] = 'The background scan process is no longer running. Completed files remain cached.'
        return state
    except (OSError, ValueError, KeyError):
        return None


def start_job(root, data, config):
    root, data = Path(root).resolve(), Path(data).resolve()
    jobs = data / 'jobs'
    jobs.mkdir(parents=True, exist_ok=True)
    # Exclusive short launch lock prevents two browser sessions from launching together.
    lock = jobs / 'launch.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('Another scan is starting. Wait a moment before retrying.')
    os.close(descriptor)
    try:
        active = current_job(data)
        if active and active['status'] in {'starting', 'running'}:
            raise ValueError('A scan is already running in the background. You can browse while it finishes.')
        directory = jobs / uuid.uuid4().hex
        directory.mkdir()
        config = {**config, 'root': str(root), 'data': str(data), 'job_directory': str(directory)}
        save_report(directory / 'config.json', config)
        save_report(directory / 'state.json', {'status': 'starting', 'started': datetime.now(timezone.utc).isoformat(),
                                              'folder': config['folder_name']})
        save_report(jobs / 'active.json', {'directory': str(directory)})
        with (directory / 'worker.log').open('ab') as output:
            options = {'cwd': str(root), 'stdin': subprocess.DEVNULL, 'stdout': output,
                       'stderr': subprocess.STDOUT, 'close_fds': True}
            if os.name == 'nt':
                # python.exe's venv launcher can create a console for its child.
                # pythonw.exe is a GUI-subsystem interpreter and never opens one.
                executable = str(Path(sys.executable).with_name('pythonw.exe'))
                if not Path(executable).exists():
                    executable = sys.executable
                options['creationflags'] = subprocess.CREATE_NO_WINDOW
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = subprocess.SW_HIDE
                options['startupinfo'] = startup
            else:
                executable = sys.executable
                options['start_new_session'] = True
            worker = subprocess.Popen([executable, '-m', 'festival_finder.worker', str(directory / 'config.json')], **options)
        (directory / 'pid.txt').write_text(str(worker.pid))
        return current_job(data)
    finally:
        lock.unlink(missing_ok=True)
