"""Launch the local read-only progress panel without a console window."""
import hashlib
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_PORT = 8503


def _identity(data):
    canonical = str(Path(data).resolve()).casefold().encode()
    return hashlib.sha256(canonical).hexdigest()


def _url(port):
    return f'http://127.0.0.1:{port}/'


def healthy(data, port):
    try:
        with urllib.request.urlopen(_url(port)+'health', timeout=.3) as response:
            return response.status == 200 and response.read().decode() == _identity(data)
    except OSError:
        return False


def _available_port():
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        return server.getsockname()[1]


def ensure_panel_server(root, data):
    root, data = Path(root).resolve(), Path(data).resolve()
    data.mkdir(parents=True, exist_ok=True)
    port_file = data / 'panel-server-port'
    try:
        port = int(port_file.read_text())
    except (OSError, ValueError):
        port = None
    for candidate in (port, DEFAULT_PORT):
        if candidate and healthy(data, candidate):
            port_file.write_text(str(candidate))
            return _url(candidate)

    lock = data / 'panel-launch.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        fd = None
    if fd is not None:
        os.close(fd)
        try:
            port = _available_port()
            port_file.write_text(str(port))
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
            with (data / 'panel-server.log').open('ab') as output:
                process = subprocess.Popen([str(executable), '-m', 'festival_finder.progress_server', str(data), str(port)],
                                           stdout=output, stderr=subprocess.STDOUT, **options)
            (data / 'panel-server.pid').write_text(str(process.pid))
        finally:
            lock.unlink(missing_ok=True)
    deadline = time.monotonic()+8
    while time.monotonic()<deadline:
        try:
            port = int(port_file.read_text())
        except (OSError, ValueError):
            port = None
        if port and healthy(data, port):
            return _url(port)
        time.sleep(.1)
    raise RuntimeError(f'Could not start the progress panel for {data}. See {data / "panel-server.log"}.')
